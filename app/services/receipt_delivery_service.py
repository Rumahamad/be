from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.enums import PaymentStatus
from app.models.identity import User
from app.models.payments import Payment
from app.services.audit_service import AuditService
from app.services.email_service import (
    EmailAttachment,
    EmailDeliveryError,
    EmailProvider,
    OutgoingEmail,
    configured_email_provider,
)
from app.services.email_templates import render_email_template
from app.services.receipt_service import ReceiptService


@dataclass(frozen=True)
class ReceiptDeliveryResult:
    receipt_no: str
    recipient: str
    provider: str
    provider_message_id: str | None


class ReceiptDeliveryService:
    def __init__(self, provider: EmailProvider | None = None) -> None:
        self.provider = provider
        self.receipts = ReceiptService()
        self.audit = AuditService()

    def send(self, db: Session, *, actor: User, payment_id: UUID) -> ReceiptDeliveryResult:
        payment = db.get(Payment, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.status != PaymentStatus.APPROVED:
            self._record_failure(db, actor, payment_id, "Payment is not approved")
            raise HTTPException(status_code=409, detail="Receipt is available after approval")

        recipient = db.get(User, payment.submitted_by)
        if not recipient or not recipient.email:
            self._record_failure(db, actor, payment_id, "Payment submitter has no email address")
            raise EmailDeliveryError("The payment submitter has no email address")

        settings = get_settings()
        provider = self.provider or configured_email_provider(settings)
        if not provider:
            self._record_failure(db, actor, payment_id, "Email delivery is not configured")
            raise EmailDeliveryError("Email delivery is not configured")

        try:
            content, receipt = self.receipts.render(db, payment_id)
            rendered = render_email_template(
                "payment_receipt",
                {
                    "title": f"Contribution receipt {receipt.receipt_no}",
                    "message": f"Your receipt for payment {payment.payment_no} is attached.",
                },
                recipient_name=recipient.display_name,
                frontend_url=settings.frontend_url,
                app_name=settings.email_app_name,
            )
            provider_message_id = provider.send(
                OutgoingEmail(
                    recipient=recipient.email,
                    subject=rendered.subject,
                    text=rendered.text,
                    html=rendered.html,
                    attachment=EmailAttachment(
                        filename=f"{receipt.receipt_no}.pdf",
                        content=content,
                        mime_type="application/pdf",
                    ),
                )
            )
        except (EmailDeliveryError, HTTPException) as exc:
            message = exc.detail if isinstance(exc, HTTPException) else str(exc)
            self._record_failure(db, actor, payment_id, str(message))
            raise

        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="payment.receipt_emailed",
            entity_type="payment",
            entity_id=payment.id,
            after_data={
                "receipt_id": str(receipt.id),
                "receipt_no": receipt.receipt_no,
                "recipient_user_id": str(recipient.id),
                "provider": provider.name,
                "provider_message_id": provider_message_id,
            },
        )
        return ReceiptDeliveryResult(
            receipt_no=receipt.receipt_no,
            recipient=recipient.email,
            provider=provider.name,
            provider_message_id=provider_message_id,
        )

    def _record_failure(
        self, db: Session, actor: User, payment_id: UUID, message: str
    ) -> None:
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="payment.receipt_email_failed",
            entity_type="payment",
            entity_id=payment_id,
            after_data={"error": message[:500]},
        )

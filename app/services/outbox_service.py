from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.communications import NotificationDelivery, NotificationOutbox
from app.models.identity import User
from app.services.email_service import (
    EmailAttachment,
    EmailDeliveryError,
    EmailProvider,
    OutgoingEmail,
    configured_email_provider,
)
from app.services.email_templates import render_email_template
from app.services.receipt_service import ReceiptService


class OutboxService:
    def __init__(self, provider: EmailProvider | None = None) -> None:
        self.provider = provider
        self.receipts = ReceiptService()

    def process_due(self, db: Session, *, limit: int = 50) -> int:
        settings = get_settings()
        provider = self.provider or configured_email_provider(settings)
        if not provider:
            return 0
        now = datetime.now(UTC)
        items = db.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.channel == "EMAIL",
                NotificationOutbox.status.in_(("PENDING", "FAILED")),
                NotificationOutbox.attempt_count < settings.notification_max_attempts,
                or_(
                    NotificationOutbox.next_retry_at.is_(None),
                    NotificationOutbox.next_retry_at <= now,
                ),
            )
            .order_by(NotificationOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        processed = 0
        for item in items:
            user = db.get(User, item.recipient_user_id)
            if not user:
                self._record_failure(db, item, provider.name, "", "Recipient user not found")
                continue
            attachment = None
            receipt_id = item.payload.get("receipt_id")
            payment_id = item.payload.get("payment_id")
            if receipt_id and payment_id:
                try:
                    content, receipt = self.receipts.render(db, UUID(str(payment_id)))
                except (ValueError, HTTPException) as exc:
                    self._record_failure(
                        db,
                        item,
                        provider.name,
                        user.email,
                        f"Receipt generation failed: {exc}",
                    )
                    continue
                attachment = EmailAttachment(
                    filename=f"{receipt.receipt_no}.pdf",
                    content=content,
                    mime_type="application/pdf",
                )
            try:
                rendered = render_email_template(
                    item.template_key,
                    item.payload,
                    recipient_name=user.display_name,
                    frontend_url=settings.frontend_url,
                    app_name=settings.email_app_name,
                )
                provider_message_id = provider.send(
                    OutgoingEmail(
                        recipient=user.email,
                        subject=rendered.subject,
                        text=rendered.text,
                        html=rendered.html,
                        attachment=attachment,
                    )
                )
            except EmailDeliveryError as exc:
                self._record_failure(db, item, provider.name, user.email, str(exc))
                continue
            item.attempt_count += 1
            item.status = "SENT"
            item.processed_at = now
            db.add(
                NotificationDelivery(
                    outbox_id=item.id,
                    provider=provider.name,
                    recipient=user.email,
                    status="SENT",
                    provider_message_id=provider_message_id,
                    attempt_no=item.attempt_count,
                )
            )
            processed += 1
        return processed

    @staticmethod
    def _record_failure(
        db: Session,
        item: NotificationOutbox,
        provider: str,
        recipient: str,
        message: str,
    ) -> None:
        item.attempt_count += 1
        item.status = "FAILED"
        retry_minutes = min(2 ** (item.attempt_count - 1), 60 * 24)
        item.next_retry_at = datetime.now(UTC) + timedelta(minutes=retry_minutes)
        db.add(
            NotificationDelivery(
                outbox_id=item.id,
                provider=provider,
                recipient=recipient,
                status="FAILED",
                error_message=message[:2000],
                attempt_no=item.attempt_count,
            )
        )

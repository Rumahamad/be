from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.engines.payment_verification.email_authentication import AUTH_VERSION
from app.models.enums import FileStatus, PaymentStatus
from app.models.files import File
from app.models.payments import Payment, PaymentFile, PaymentRevision
from app.models.verification import (
    IncomingUpiCredit,
    PaymentProofExtraction,
    PaymentVerificationEvent,
    PaymentUtrClaim,
)
from app.services.payment_utr_service import lock_reference
from app.services.payment_service import PaymentService
from app.services.payment_verification_readiness import ready_payment


class PaymentReconciliationService:
    def __init__(self) -> None:
        self.payments = PaymentService()

    def reconcile_payment(self, db: Session, payment_id: UUID, actor_user_id: UUID, *, approve_verified: bool = False) -> str:
        payment = db.scalar(select(Payment).where(
            Payment.id == payment_id,
        ).with_for_update())
        if not payment or payment.status != PaymentStatus.PENDING_VERIFICATION:
            return "NOT_PENDING"
        if not db.scalar(select(Payment.id).where(Payment.id == payment_id, ready_payment())):
            return "AWAITING_SUBMISSION"
        proof_ids = set(db.scalars(select(PaymentFile.file_id)
            .join(PaymentRevision, PaymentRevision.id == PaymentFile.payment_revision_id)
            .join(File, File.id == PaymentFile.file_id)
            .where(PaymentFile.payment_id == payment.id,
                   PaymentRevision.revision_no == payment.current_revision,
                   File.status == FileStatus.ACTIVE)).all())
        extractions = db.scalars(select(PaymentProofExtraction).where(
            PaymentProofExtraction.payment_id == payment.id,
            PaymentProofExtraction.payment_revision == payment.current_revision,
            PaymentProofExtraction.proof_file_id.in_(proof_ids),
        )).all()
        if not proof_ids or {item.proof_file_id for item in extractions} != proof_ids:
            payment.verification_status = "WAITING"
            payment.verification_error_code = "OCR_INCOMPLETE"
            return "OCR_INCOMPLETE"
        if any(item.status != "REFERENCE_FOUND" for item in extractions):
            payment.verification_status = "ADMIN_REVIEW"
            payment.verification_error_code = next(
                (item.error_code for item in extractions if item.error_code), "OCR_INCOMPLETE"
            )
            return "OCR_INCOMPLETE"
        refs = {item.selected_upi_reference for item in extractions if item.selected_upi_reference}
        if not refs:
            payment.verification_status = "OCR_REFERENCE_NOT_FOUND"
            payment.verification_error_code = "OCR_REFERENCE_NOT_FOUND"
            return "NO_REFERENCE"
        if len(refs) != 1:
            payment.verification_status = "ADMIN_REVIEW"
            payment.verification_error_code = "OCR_REFERENCE_AMBIGUOUS"
            return "AMBIGUOUS_REFERENCE"
        return self._match(db, payment, refs.pop(), actor_user_id, approve_verified=approve_verified)

    def reconcile_reference(self, db: Session, reference: str, actor_user_id: UUID) -> list[str]:
        payment_ids = db.scalars(
            select(PaymentProofExtraction.payment_id)
            .join(Payment, Payment.id == PaymentProofExtraction.payment_id)
            .where(
                PaymentProofExtraction.selected_upi_reference == reference,
                PaymentProofExtraction.payment_revision == Payment.current_revision,
                Payment.status == PaymentStatus.PENDING_VERIFICATION,
            )
            .distinct()
        ).all()
        return [self.reconcile_payment(db, payment_id, actor_user_id) for payment_id in payment_ids]

    def _match(self, db: Session, payment: Payment, reference: str, actor_user_id: UUID, *, approve_verified: bool = False) -> str:
        lock_reference(db, reference)
        claim = db.get(PaymentUtrClaim, reference)
        if claim is not None:
            payment.verification_status = 'DUPLICATE_REFERENCE'
            payment.verification_error_code = 'UTR_ALREADY_CONSUMED'
            self._event(db, payment, 'RECONCILIATION_DUPLICATE_REFERENCE', reference)
            return 'DUPLICATE_REFERENCE'
        claim_count = db.scalar(
            select(func.count(func.distinct(PaymentProofExtraction.payment_id)))
            .join(Payment, Payment.id == PaymentProofExtraction.payment_id)
            .where(
                PaymentProofExtraction.selected_upi_reference == reference,
                PaymentProofExtraction.payment_revision == Payment.current_revision,
                Payment.status.in_((PaymentStatus.PENDING_VERIFICATION,
                                    PaymentStatus.APPROVED, PaymentStatus.REVERSED)),
            )
        ) or 0
        if claim_count != 1:
            payment.verification_status = "DUPLICATE_REFERENCE"
            payment.verification_error_code = "DUPLICATE_REFERENCE"
            self._event(db, payment, "RECONCILIATION_DUPLICATE_REFERENCE", reference)
            return "DUPLICATE_REFERENCE"

        credit = db.scalar(select(IncomingUpiCredit).where(
            IncomingUpiCredit.upi_reference == reference,
        ).with_for_update())
        if not credit:
            untrusted_credit = db.scalar(select(IncomingUpiCredit).where(
                IncomingUpiCredit.observed_upi_reference == reference,
                IncomingUpiCredit.parse_status.in_(("REJECTED", "REVIEW_REQUIRED")),
            ).order_by(IncomingUpiCredit.message_received_at.desc()).limit(1))
            if untrusted_credit:
                payment.verification_status = "ADMIN_REVIEW"
                payment.verification_error_code = (
                    "FORWARDED_EMAIL_REVIEW_REQUIRED"
                    if untrusted_credit.parse_status == "REVIEW_REQUIRED"
                    else "UNTRUSTED_EMAIL_CREDIT"
                )
                self._event(
                    db, payment, "RECONCILIATION_UNTRUSTED_EMAIL",
                    reference, untrusted_credit.id,
                )
                return "EMAIL_REVIEW_REQUIRED"
            payment.verification_status = "WAITING_FOR_EMAIL_MATCH"
            payment.verification_error_code = None
            return "WAITING_FOR_EMAIL"
        if (
            credit.parse_status != "READY"
            or not credit.sender_verified
            or not credit.recipient_account_matches
            or not credit.authentication_evidence.get('verified')
            or credit.authentication_evidence.get('version') != AUTH_VERSION
        ):
            payment.verification_status = "ADMIN_REVIEW"
            payment.verification_error_code = "UNTRUSTED_EMAIL_CREDIT"
            self._event(db, payment, "RECONCILIATION_UNTRUSTED_EMAIL", reference, credit.id)
            return "UNTRUSTED_EMAIL"
        if credit.consumed_at or (credit.matched_payment_id and credit.matched_payment_id != payment.id):
            payment.verification_status = "DUPLICATE_REFERENCE"
            payment.verification_error_code = "DUPLICATE_REFERENCE"
            self._event(db, payment, "RECONCILIATION_DUPLICATE_REFERENCE", reference, credit.id)
            return "DUPLICATE_REFERENCE"
        if Decimal(payment.total_amount) != Decimal(credit.amount or 0):
            payment.verification_status = "AMOUNT_MISMATCH"
            payment.verification_error_code = "AMOUNT_MISMATCH"
            self._event(db, payment, "RECONCILIATION_AMOUNT_MISMATCH", reference, credit.id)
            return "AMOUNT_MISMATCH"

        settings = get_settings()
        payment.verification_status = "EMAIL_MATCHED"
        payment.verification_error_code = None
        self._event(db, payment, "RECONCILIATION_MATCHED", reference, credit.id)
        if not approve_verified and (not settings.payment_auto_verify_enabled or settings.payment_auto_verify_shadow_mode):
            self._event(db, payment, "AUTO_APPROVAL_SHADOW_MATCH", reference, credit.id)
            return "SHADOW_MATCH"

        now = datetime.now(UTC)
        credit.matched_payment_id = payment.id
        credit.matched_at = now
        if not approve_verified:
            payment.auto_verified_at = now
        payment.auto_verified_reference = reference
        credit.consumed_at = now
        self.payments.approve(
            db,
            payment.id,
            actor_user_id,
            comment="Exact authenticated HDFC UTR, amount and account match",
            verification_method="HDFC_EMAIL_ADMIN" if approve_verified else "HDFC_EMAIL",
            incoming_credit_id=credit.id,
        )
        if not approve_verified:
            from app.services.audit_service import AuditService
            AuditService().record(
                db, actor_user_id=actor_user_id, action='payment.auto_approved',
                entity_type='payment', entity_id=payment.id,
                after_data={'revision': payment.current_revision,
                            'incoming_credit_id': str(credit.id),
                            'mode': 'AUTO', 'approved_at': now.isoformat()},
            )
        return "VERIFIED_APPROVED" if approve_verified else "AUTO_APPROVED"

    @staticmethod
    def _event(
        db: Session,
        payment: Payment,
        event_type: str,
        reference: str,
        credit_id: UUID | None = None,
    ) -> None:
        # Periodic retries should not append identical audit events endlessly.
        if db.scalar(select(PaymentVerificationEvent.id).where(
            PaymentVerificationEvent.payment_id == payment.id,
            PaymentVerificationEvent.event_type == event_type,
            PaymentVerificationEvent.incoming_credit_id == credit_id,
            PaymentVerificationEvent.upi_reference_masked == f"********{reference[-4:]}",
            PaymentVerificationEvent.metadata_json["revision"].as_integer() == payment.current_revision,
        ).limit(1)):
            return
        db.add(PaymentVerificationEvent(
            payment_id=payment.id,
            event_type=event_type,
            actor_type="SYSTEM",
            incoming_credit_id=credit_id,
            upi_reference_masked=f"********{reference[-4:]}",
            metadata_json={"revision": payment.current_revision,
                           "mode": 'SHADOW' if get_settings().payment_auto_verify_shadow_mode else
                           'AUTO' if get_settings().payment_auto_verify_enabled else 'DISABLED'},
        ))

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.backup import GoogleConnection
from app.services.gmail_verification_oauth_service import PURPOSE
from app.services.payment_proof_ocr_service import PaymentProofOcrService
from app.services.payment_reconciliation_service import PaymentReconciliationService


def process_payment_proof(payment_id: UUID, *, force: bool = False) -> int:
    with SessionLocal() as db:
        processed = PaymentProofOcrService().process_payment(db, payment_id, force=force)
        # Retain extraction evidence even if reconciliation/provider state fails.
        db.commit()
        connection = db.scalar(select(GoogleConnection).where(
            GoogleConnection.purpose == PURPOSE,
            GoogleConnection.status == "ACTIVE",
        ))
        if connection:
            PaymentReconciliationService().reconcile_payment(db, payment_id, connection.connected_by)
        db.commit()
        return processed


def process_pending_payment_proofs(limit: int = 20) -> int:
    with SessionLocal() as db:
        payment_ids = []
        # Let the service perform the eligibility query and OCR in one session.
        processed = PaymentProofOcrService().process_pending(db, limit=limit)
        if processed:
            connection = db.scalar(select(GoogleConnection).where(
                GoogleConnection.purpose == PURPOSE,
                GoogleConnection.status == "ACTIVE",
            ))
            if connection:
                from app.models.enums import PaymentStatus
                from app.models.payments import Payment
                payment_ids = db.scalars(
                    select(Payment.id).where(Payment.status == PaymentStatus.PENDING_VERIFICATION)
                ).all()
                reconciliation = PaymentReconciliationService()
                for payment_id in payment_ids:
                    reconciliation.reconcile_payment(db, payment_id, connection.connected_by)
        db.commit()
        return processed

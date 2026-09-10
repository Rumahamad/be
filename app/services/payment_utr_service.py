from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.models.verification import PaymentUtrClaim


def lock_reference(db: Session, reference: str) -> None:
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:reference, 710022))'),
               {'reference': reference})


def claim_reference(db: Session, reference: str, payment_id: UUID) -> None:
    lock_reference(db, reference)
    claim = db.get(PaymentUtrClaim, reference)
    if claim and claim.payment_id != payment_id:
        raise HTTPException(409, 'This UTR has already been used to approve another payment')
    if not claim:
        db.add(PaymentUtrClaim(reference=reference, payment_id=payment_id))
        db.flush()

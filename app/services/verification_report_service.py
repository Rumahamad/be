"""Read-only payment matching report. Evidence never grants approval."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.engines.payment_verification.email_authentication import AUTH_VERSION

from app.models.enums import FileStatus
from app.models.files import File
from app.models.payments import Payment, PaymentFile, PaymentRevision
from app.models.identity import User
from app.models.verification import IncomingUpiCredit, PaymentProofExtraction
from app.schemas.verification import PaymentMatchOutput


def payment_match_report(db: Session, limit: int = 50) -> list[PaymentMatchOutput]:
    rows = db.execute(select(Payment, User.display_name)
        .join(User, User.id == Payment.submitted_by)
        .order_by(Payment.created_at.desc()).limit(limit)).all()
    ids = [payment.id for payment, _ in rows]
    proofs = db.execute(select(PaymentFile.payment_id, PaymentFile.file_id)
        .join(PaymentRevision, PaymentRevision.id == PaymentFile.payment_revision_id)
        .join(Payment, Payment.id == PaymentFile.payment_id)
        .join(File, File.id == PaymentFile.file_id)
        .where(Payment.id.in_(ids), PaymentRevision.revision_no == Payment.current_revision,
               File.status == FileStatus.ACTIVE)).all()
    active = {}
    for payment_id, file_id in proofs:
        active.setdefault(payment_id, set()).add(file_id)
    extractions = db.scalars(select(PaymentProofExtraction)
        .join(Payment, Payment.id == PaymentProofExtraction.payment_id)
        .where(Payment.id.in_(ids),
               PaymentProofExtraction.payment_revision == Payment.current_revision)).all()
    by_payment = {}
    for extraction in extractions:
        if extraction.proof_file_id in active.get(extraction.payment_id, set()):
            by_payment.setdefault(extraction.payment_id, []).append(extraction)
    references = {e.selected_upi_reference for e in extractions if e.selected_upi_reference}
    credits = db.scalars(select(IncomingUpiCredit).where(
        IncomingUpiCredit.observed_upi_reference.in_(references)
        | IncomingUpiCredit.upi_reference.in_(references))
        .order_by(IncomingUpiCredit.message_received_at.desc())).all()
    by_reference = {}
    for credit in credits:
        ref = credit.observed_upi_reference or credit.upi_reference
        previous = by_reference.get(ref)
        if previous is None or (credit.parse_status == 'READY' and previous.parse_status != 'READY'):
            by_reference[ref] = credit
    result = []
    for payment, name in rows:
        evidence = by_payment.get(payment.id, [])
        refs = sorted({e.selected_upi_reference for e in evidence if e.selected_upi_reference})
        complete = bool(active.get(payment.id)) and len(evidence) == len(active[payment.id])
        ocr_state = ('NOT_UPLOADED' if not active.get(payment.id) else
                     'PROCESSING' if not complete else
                     'AMBIGUOUS' if len(refs) > 1 else
                     'READ' if len(refs) == 1 and all(e.status == 'REFERENCE_FOUND' for e in evidence)
                     else 'NEEDS_REVIEW')
        credit = by_reference.get(refs[0]) if len(refs) == 1 else None
        result.append(PaymentMatchOutput(
            payment_id=payment.id, payment_no=payment.payment_no, member_name=name,
            payment_status=payment.status.value, amount=payment.total_amount,
            screenshot_status=ocr_state, screenshot_utrs=refs,
            email_utr=(credit.observed_upi_reference or credit.upi_reference) if credit else None,
            email_amount=credit.amount if credit else None,
            reference_matches=True if credit else None,
            amount_matches=(credit.amount == payment.total_amount) if credit else None,
            account_matches=credit.recipient_account_matches if credit else None,
            email_authenticated=(credit.sender_verified and credit.parse_status == 'READY'
                                 and bool(credit.authentication_evidence.get('verified'))
                                 and credit.authentication_evidence.get('version') == AUTH_VERSION) if credit else None,
            verification_status=payment.verification_status,
            reason=payment.verification_error_code,
        ))
    return result

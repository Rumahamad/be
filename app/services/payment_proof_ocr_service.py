from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.payment_verification.screenshot_ocr import (
    OcrProcessingError,
    OcrUnavailableError,
    TesseractScreenshotOcr,
)
from app.models.enums import FileStatus, PaymentStatus
from app.models.files import File as FileRecord
from app.models.payments import Payment, PaymentFile, PaymentRevision
from app.models.verification import PaymentProofExtraction, PaymentVerificationEvent
from app.services.storage_service import StorageError, SupabaseStorageService
from app.services.payment_verification_readiness import ready_payment


class PaymentProofOcrService:
    def __init__(self) -> None:
        self.storage = SupabaseStorageService()
        self.ocr = TesseractScreenshotOcr()

    def process_payment(self, db: Session, payment_id: UUID, *, force: bool = False) -> int:
        payment = db.scalar(select(Payment).where(
            Payment.id == payment_id, ready_payment(),
        ).with_for_update())
        if not payment or payment.status != PaymentStatus.PENDING_VERIFICATION:
            return 0
        rows = db.execute(
            select(PaymentFile, FileRecord)
            .join(PaymentRevision, PaymentRevision.id == PaymentFile.payment_revision_id)
            .join(FileRecord, FileRecord.id == PaymentFile.file_id)
            .where(
                PaymentFile.payment_id == payment.id,
                PaymentRevision.revision_no == payment.current_revision,
                FileRecord.status == FileStatus.ACTIVE,
            )
            .order_by(PaymentFile.created_at.asc())
        ).all()
        processed = 0
        for _link, file_record in rows:
            existing = db.scalar(select(PaymentProofExtraction).where(
                PaymentProofExtraction.payment_id == payment.id,
                PaymentProofExtraction.proof_file_id == file_record.id,
            ))
            if existing and not force:
                continue
            extraction = existing or PaymentProofExtraction(
                payment_id=payment.id,
                proof_file_id=file_record.id,
                payment_revision=payment.current_revision,
                reference_candidates=[],
                ocr_engine="TESSERACT",
                status="PENDING",
            )
            if existing is None:
                db.add(extraction)
            extraction.selected_upi_reference = None
            extraction.reference_candidates = []
            extraction.raw_ocr_text = None
            extraction.ocr_confidence = None
            try:
                content, _ = self.storage.download(file_record.bucket_name, file_record.object_key)
                result = self.ocr.extract(content)
                extraction.raw_ocr_text = result.text
                extraction.reference_candidates = [
                    {"value": item.value, "score": str(item.score), "context": item.context}
                    for item in result.candidates
                ]
                extraction.selected_upi_reference = result.selected_reference
                extraction.ocr_confidence = result.confidence
                extraction.ocr_engine = result.engine
                extraction.ocr_engine_version = result.engine_version
                extraction.status = "REFERENCE_FOUND" if result.selected_reference else "NO_REFERENCE"
                extraction.error_code = None if result.selected_reference else "OCR_REFERENCE_NOT_FOUND"
            except OcrUnavailableError:
                extraction.status = "ERROR"
                extraction.error_code = "OCR_ENGINE_UNAVAILABLE"
            except (OcrProcessingError, StorageError):
                extraction.status = "ERROR"
                extraction.error_code = "OCR_PROCESSING_FAILED"
            db.flush()
            db.add(PaymentVerificationEvent(
                payment_id=payment.id,
                event_type=(
                    "PROOF_REFERENCE_FOUND"
                    if extraction.selected_upi_reference
                    else "PROOF_REFERENCE_NOT_FOUND"
                    if extraction.status == "NO_REFERENCE"
                    else "PROOF_OCR_FAILED"
                ),
                actor_type="SYSTEM",
                upi_reference_masked=(
                    f"********{extraction.selected_upi_reference[-4:]}"
                    if extraction.selected_upi_reference else None
                ),
                metadata_json={
                    "revision": payment.current_revision,
                    "file_id": str(file_record.id),
                    "status": extraction.status,
                    "error_code": extraction.error_code,
                },
            ))
            processed += 1

        if not processed:
            return 0
        references = set(db.scalars(select(PaymentProofExtraction.selected_upi_reference).where(
            PaymentProofExtraction.payment_id == payment.id,
            PaymentProofExtraction.payment_revision == payment.current_revision,
            PaymentProofExtraction.selected_upi_reference.is_not(None),
        )).all())
        if len(references) == 1:
            payment.verification_status = "OCR_REFERENCE_FOUND"
            payment.verification_error_code = None
        elif len(references) > 1:
            payment.verification_status = "ADMIN_REVIEW"
            payment.verification_error_code = "OCR_REFERENCE_AMBIGUOUS"
        elif rows:
            payment.verification_status = "OCR_REFERENCE_NOT_FOUND"
            payment.verification_error_code = "OCR_REFERENCE_NOT_FOUND"
        return processed

    def process_pending(self, db: Session, limit: int = 20) -> int:
        payment_ids = db.scalars(
            select(Payment.id)
            .where(Payment.status == PaymentStatus.PENDING_VERIFICATION, ready_payment())
            .order_by(Payment.submitted_at.asc())
            .limit(limit)
        ).all()
        return sum(self.process_payment(db, payment_id) for payment_id in payment_ids)

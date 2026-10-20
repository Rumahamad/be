from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import user_has_permission
from app.config.settings import get_settings
from app.constants.permissions import PAYMENT_CREATE_ANY
from app.models.enums import FileStatus, PaymentStatus
from app.models.files import File as FileRecord
from app.models.identity import User
from app.models.payments import Payment, PaymentFile, PaymentRevision
from app.schemas.payments import PaymentFileOutput
from app.services.storage_service import StorageError, StorageService

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILES_PER_REVISION = 5


class PaymentFileService:
    def __init__(self, storage=None) -> None:
        self.storage = storage or StorageService()

    def upload(
        self,
        db: Session,
        user: User,
        payment_id: UUID,
        *,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> PaymentFileOutput:
        # Serialize uploads for one payment so two concurrent requests cannot both
        # observe four files and create a sixth file.
        payment = db.scalar(
            select(Payment).where(Payment.id == payment_id).with_for_update()
        )
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.status != PaymentStatus.PENDING_VERIFICATION:
            raise HTTPException(status_code=409, detail="Screenshots can only be added to pending payments")
        if payment.submitted_by != user.id and not user_has_permission(db, user, PAYMENT_CREATE_ANY):
            raise HTTPException(status_code=403, detail="You cannot add files to this payment")
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP screenshots are supported")

        max_size = get_settings().storage_max_file_bytes
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail="Each screenshot must be 5 MB or smaller")
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded screenshot is empty")

        revision = db.scalar(
            select(PaymentRevision).where(
                PaymentRevision.payment_id == payment.id,
                PaymentRevision.revision_no == payment.current_revision,
            )
        )
        if not revision:
            raise HTTPException(status_code=409, detail="Payment revision is unavailable")

        existing_count = db.scalar(
            select(func.count(PaymentFile.id)).where(
                PaymentFile.payment_id == payment.id,
                PaymentFile.payment_revision_id == revision.id,
            )
        ) or 0
        if existing_count >= MAX_FILES_PER_REVISION:
            raise HTTPException(status_code=409, detail="A payment can have at most five screenshots")

        suffix = PurePosixPath(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = mimetypes.guess_extension(mime_type) or ".bin"
        object_key = f"payments/{payment.id}/revisions/{payment.current_revision}/{uuid4()}{suffix}"
        bucket = get_settings().storage_bucket
        try:
            self.storage.upload(bucket, object_key, content, mime_type)
        except StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        file_record = FileRecord(
            storage_provider=get_settings().storage_provider,
            bucket_name=bucket,
            object_key=object_key,
            original_name=(filename or "screenshot")[:255],
            mime_type=mime_type,
            size_bytes=len(content),
            uploaded_by=user.id,
            status=FileStatus.ACTIVE,
        )
        try:
            db.add(file_record)
            db.flush()
            link = PaymentFile(
                payment_id=payment.id,
                payment_revision_id=revision.id,
                file_id=file_record.id,
                uploaded_by=user.id,
            )
            db.add(link)
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            self._cleanup(bucket, object_key)
            raise HTTPException(status_code=409, detail="The screenshot could not be recorded") from exc
        db.refresh(link)
        return PaymentFileOutput(
            id=file_record.id,
            original_name=file_record.original_name,
            mime_type=file_record.mime_type,
            size_bytes=file_record.size_bytes,
            revision_no=payment.current_revision,
        )

    def download(self, db: Session, user: User, payment_id: UUID, file_id: UUID) -> tuple[bytes, str, str]:
        row = db.execute(
            select(PaymentFile, FileRecord, Payment)
            .join(FileRecord, FileRecord.id == PaymentFile.file_id)
            .join(Payment, Payment.id == PaymentFile.payment_id)
            .where(PaymentFile.payment_id == payment_id, PaymentFile.file_id == file_id)
        ).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Payment screenshot not found")
        _payment_file, file_record, payment = row
        if payment.submitted_by != user.id and not user_has_permission(db, user, PAYMENT_CREATE_ANY):
            raise HTTPException(status_code=403, detail="You cannot view this payment screenshot")
        if file_record.status != FileStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="Payment screenshot is unavailable")
        try:
            content, provider_type = self.storage.download(file_record.bucket_name, file_record.object_key)
        except StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return content, provider_type or file_record.mime_type, file_record.original_name

    def list_files(self, db: Session, user: User, payment_id: UUID) -> list[PaymentFileOutput]:
        payment = db.get(Payment, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.submitted_by != user.id and not user_has_permission(db, user, PAYMENT_CREATE_ANY):
            raise HTTPException(status_code=403, detail="You cannot view this payment screenshot")
        revision = db.scalar(
            select(PaymentRevision).where(
                PaymentRevision.payment_id == payment.id,
                PaymentRevision.revision_no == payment.current_revision,
            )
        )
        if not revision:
            return []
        rows = db.execute(
            select(PaymentFile, FileRecord)
            .join(FileRecord, FileRecord.id == PaymentFile.file_id)
            .where(
                PaymentFile.payment_id == payment.id,
                PaymentFile.payment_revision_id == revision.id,
                FileRecord.status == FileStatus.ACTIVE,
            )
            .order_by(PaymentFile.created_at.asc())
        ).all()
        return [
            PaymentFileOutput(
                id=file_record.id,
                original_name=file_record.original_name,
                mime_type=file_record.mime_type,
                size_bytes=file_record.size_bytes,
                revision_no=payment.current_revision,
            )
            for _link, file_record in rows
        ]

    def _cleanup(self, bucket: str, object_key: str) -> None:
        try:
            self.storage.delete(bucket, object_key)
        except StorageError:
            pass

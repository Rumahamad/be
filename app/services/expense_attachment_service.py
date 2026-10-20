from __future__ import annotations

import re
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import user_has_permission
from app.config.settings import get_settings
from app.constants.permissions import EXPENSE_VIEW_DETAILS, EXPENSE_VIEW_SUMMARY
from app.models.enums import FileStatus
from app.models.expenses import Expense, ExpenseAttachment
from app.models.files import File as FileRecord
from app.models.identity import User
from app.models.settings import OrganizationSetting
from app.repositories.expenses import ExpenseRepository
from app.schemas.expenses import ExpenseAttachmentOutput
from app.services.storage_service import StorageError, StorageService

ALLOWED_EXPENSE_FILE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_ATTACHMENTS_PER_EXPENSE = 10


class ExpenseAttachmentService:
    def __init__(
        self,
        repository: ExpenseRepository | None = None,
        storage=None,
    ) -> None:
        self.repository = repository or ExpenseRepository()
        self.storage = storage or StorageService()

    def upload(
        self,
        db: Session,
        user: User,
        expense_id: UUID,
        *,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> ExpenseAttachmentOutput:
        expense = self.repository.expense_for_update(db, expense_id)
        if not expense:
            raise HTTPException(status_code=404, detail="Expense not found")
        if expense.status != "POSTED":
            raise HTTPException(status_code=409, detail="Attachments cannot be added to a reversed expense")
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded attachment is empty")
        normalized_type = mime_type.partition(";")[0].strip().lower()
        suffix = ALLOWED_EXPENSE_FILE_TYPES.get(normalized_type)
        if not suffix or not self._matches_signature(content, normalized_type):
            raise HTTPException(
                status_code=415, detail="Only valid JPEG, PNG, and WebP files are supported"
            )
        max_size = get_settings().storage_max_file_bytes
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail="Attachment exceeds configured size limit")
        if self.repository.attachment_count(db, expense.id) >= MAX_ATTACHMENTS_PER_EXPENSE:
            raise HTTPException(status_code=409, detail="An expense can have at most ten attachments")

        normalized_name = (filename or "attachment").replace("\\", "/")
        safe_stem = re.sub(r"[\x00-\x1f\x7f]", "_", PurePosixPath(normalized_name).name)[:255]
        object_key = f"expenses/{expense.id}/{uuid4()}{suffix}"
        bucket = get_settings().storage_bucket
        try:
            self.storage.upload(bucket, object_key, content, normalized_type)
        except StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        file_record = FileRecord(
            storage_provider=get_settings().storage_provider,
            bucket_name=bucket,
            object_key=object_key,
            original_name=safe_stem or f"attachment{suffix}",
            mime_type=normalized_type,
            size_bytes=len(content),
            uploaded_by=user.id,
            status=FileStatus.ACTIVE,
        )
        try:
            db.add(file_record)
            db.flush()
            link = ExpenseAttachment(
                expense_id=expense.id,
                file_id=file_record.id,
                uploaded_by=user.id,
            )
            db.add(link)
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            self._cleanup(bucket, object_key)
            raise HTTPException(status_code=409, detail="The attachment could not be recorded") from exc
        db.refresh(link)
        return self.output(expense.id, link, file_record)

    def list_files(
        self, db: Session, user: User, expense_id: UUID
    ) -> list[ExpenseAttachmentOutput]:
        self._ensure_can_view(db, user, expense_id)
        return [
            self.output(expense_id, link, file_record)
            for link, file_record in self.repository.list_attachments(db, expense_id)
        ]

    def download(
        self, db: Session, user: User, expense_id: UUID, file_id: UUID
    ) -> tuple[bytes, str, str]:
        self._ensure_can_view(db, user, expense_id)
        row = self.repository.attachment(db, expense_id, file_id)
        if not row:
            raise HTTPException(status_code=404, detail="Expense attachment not found")
        _link, file_record = row
        try:
            content, provider_type = self.storage.download(
                file_record.bucket_name, file_record.object_key
            )
        except StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return content, provider_type or file_record.mime_type, file_record.original_name

    def _ensure_can_view(self, db: Session, user: User, expense_id: UUID) -> None:
        if not db.get(Expense, expense_id):
            raise HTTPException(status_code=404, detail="Expense not found")
        if user_has_permission(db, user, EXPENSE_VIEW_DETAILS):
            return
        if not user_has_permission(db, user, EXPENSE_VIEW_SUMMARY):
            raise HTTPException(status_code=403, detail="Expense access is unavailable")
        setting = db.scalar(select(OrganizationSetting).limit(1))
        if not setting or setting.expense_visibility != "DETAILS" or (
            "attachments" not in (setting.expense_visible_fields or [])
        ):
            raise HTTPException(status_code=403, detail="Expense attachments are not visible")

    @staticmethod
    def _matches_signature(content: bytes, mime_type: str) -> bool:
        if mime_type == "image/jpeg":
            return content.startswith(b"\xff\xd8\xff")
        if mime_type == "image/png":
            return content.startswith(b"\x89PNG\r\n\x1a\n")
        if mime_type == "image/webp":
            return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
        return False

    @staticmethod
    def output(
        expense_id: UUID, link: ExpenseAttachment, file_record: FileRecord
    ) -> ExpenseAttachmentOutput:
        return ExpenseAttachmentOutput(
            id=file_record.id,
            original_name=file_record.original_name,
            mime_type=file_record.mime_type,
            size_bytes=file_record.size_bytes,
            created_at=link.created_at,
            download_url=f"/api/v1/expenses/{expense_id}/attachments/{file_record.id}",
        )

    def _cleanup(self, bucket: str, object_key: str) -> None:
        try:
            self.storage.delete(bucket, object_key)
        except StorageError:
            pass

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.enums import FileStatus, UserStatus
from app.models.files import File as FileRecord
from app.models.identity import User
from app.services.storage_service import StorageError, SupabaseStorageService

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PROFILE_BYTES = 2 * 1024 * 1024


class ProfilePictureService:
    def __init__(self, storage: SupabaseStorageService | None = None) -> None:
        self.storage = storage or SupabaseStorageService()

    def upload(
        self,
        db: Session,
        actor: User,
        member_id: UUID,
        *,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> str:
        member = db.get(User, member_id)
        if not member or member.status == UserStatus.DELETED:
            raise HTTPException(status_code=404, detail="Member not found")
        self._validate(content, mime_type)
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = mimetypes.guess_extension(mime_type) or ".bin"
        bucket = get_settings().supabase_storage_bucket
        object_key = f"profiles/{member.id}/{uuid4()}{suffix}"
        try:
            self.storage.upload(bucket, object_key, content, mime_type)
        except StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        previous = db.get(FileRecord, member.profile_picture_file_id) if member.profile_picture_file_id else None
        record = FileRecord(
            bucket_name=bucket,
            object_key=object_key,
            original_name=(filename or "profile-picture")[:255],
            mime_type=mime_type,
            size_bytes=len(content),
            uploaded_by=actor.id,
            status=FileStatus.ACTIVE,
        )
        db.add(record)
        db.flush()
        member.profile_picture_file_id = record.id
        db.commit()
        if previous:
            self._delete_file(db, previous)
        return f"/api/v1/members/{member.id}/profile-picture"

    def download(self, db: Session, member_id: UUID) -> tuple[bytes, str]:
        member = db.get(User, member_id)
        if not member or not member.profile_picture_file_id:
            raise HTTPException(status_code=404, detail="Profile picture not found")
        record = db.get(FileRecord, member.profile_picture_file_id)
        if not record or record.status != FileStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="Profile picture not found")
        try:
            content, provider_type = self.storage.download(record.bucket_name, record.object_key)
        except StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return content, provider_type or record.mime_type

    def delete(self, db: Session, member_id: UUID) -> None:
        member = db.get(User, member_id)
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        if not member.profile_picture_file_id:
            return
        record = db.get(FileRecord, member.profile_picture_file_id)
        member.profile_picture_file_id = None
        db.flush()
        if record:
            self._delete_file(db, record, commit=False)
        db.commit()

    def _delete_file(
        self, db: Session, record: FileRecord, *, commit: bool = True
    ) -> None:
        try:
            self.storage.delete(record.bucket_name, record.object_key)
        except StorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        db.delete(record)
        if commit:
            db.commit()

    @staticmethod
    def _validate(content: bytes, mime_type: str) -> None:
        if mime_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=415, detail="Use a JPEG, PNG, or WebP image")
        if not content:
            raise HTTPException(status_code=400, detail="The profile picture is empty")
        if len(content) > MAX_PROFILE_BYTES:
            raise HTTPException(status_code=413, detail="Profile pictures must be 2 MB or smaller")
        signatures = {
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        }
        if not signatures[mime_type]:
            raise HTTPException(status_code=415, detail="The selected file is not a valid image")

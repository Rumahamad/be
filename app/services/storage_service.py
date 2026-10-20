from __future__ import annotations

import httpx
import mimetypes
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.config.settings import Settings, get_settings


class StorageError(Exception):
    pass


class SupabaseStorageService:
    name = "SUPABASE"
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def upload(self, bucket: str, object_key: str, content: bytes, mime_type: str) -> None:
        response = self._request(
            "POST",
            f"/storage/v1/object/{bucket}/{object_key}",
            content=content,
            headers={"Content-Type": mime_type, "x-upsert": "false"},
        )
        if not response.is_success:
            raise StorageError(self._error_message(response, "File upload failed"))

    def ensure_private_bucket(
        self,
        bucket: str,
        *,
        max_file_bytes: int,
        allowed_mime_types: list[str],
    ) -> bool:
        """Create the configured private bucket when it does not already exist."""
        response = self._request("GET", f"/storage/v1/bucket/{bucket}")
        if response.is_success:
            return False
        if not self._is_missing_bucket(response):
            raise StorageError(self._error_message(response, "Storage bucket check failed"))

        response = self._request(
            "POST",
            "/storage/v1/bucket",
            json={
                "id": bucket,
                "name": bucket,
                "public": False,
                "file_size_limit": max_file_bytes,
                "allowed_mime_types": allowed_mime_types,
            },
        )
        if not response.is_success:
            raise StorageError(self._error_message(response, "Storage bucket creation failed"))
        return True

    def delete(self, bucket: str, object_key: str) -> None:
        response = self._request(
            "DELETE",
            f"/storage/v1/object/{bucket}",
            json={"prefixes": [object_key]},
        )
        if not response.is_success:
            raise StorageError(self._error_message(response, "Uploaded file cleanup failed"))

    def download(self, bucket: str, object_key: str) -> tuple[bytes, str | None]:
        response = self._request("GET", f"/storage/v1/object/{bucket}/{object_key}")
        if not response.is_success:
            raise StorageError(self._error_message(response, "File download failed"))
        return response.content, response.headers.get("content-type")

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        key = self.settings.supabase_admin_api_key
        if not key:
            raise StorageError("SUPABASE_SECRET_KEY is not configured")
        headers = {"apikey": key, **kwargs.pop("headers", {})}
        if not key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {key}"
        try:
            return httpx.request(
                method,
                f"{self.settings.supabase_url.rstrip('/')}{path}",
                headers=headers,
                timeout=30,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise StorageError("Supabase Storage is unavailable") from exc

    @staticmethod
    def _error_message(response: httpx.Response, fallback: str) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            message = (
                payload.get("message")
                or payload.get("msg")
                or payload.get("error")
                or payload.get("error_description")
            )
            if message:
                return str(message)
        return fallback

    @staticmethod
    def _is_missing_bucket(response: httpx.Response) -> bool:
        try:
            payload = response.json()
        except ValueError:
            return response.status_code == 404
        return response.status_code == 404 or (
            isinstance(payload, dict)
            and (payload.get("code") == "NoSuchBucket" or str(payload.get("statusCode")) == "404")
        )


class LocalStorageService:
    name = "LOCAL"

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.root = Path(self.settings.local_storage_root).resolve()

    def _path(self, bucket, object_key=""):
        for value in (bucket, object_key):
            if (not value and value == bucket) or "\\" in value or ":" in value:
                raise StorageError("Invalid storage path")
            if PurePosixPath(value).is_absolute() or any(
                    part in {"", ".", ".."} or part.endswith((" ", "."))
                    or part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL",
                        *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                    for part in value.split("/") if value):
                raise StorageError("Invalid storage path")
        if "/" in bucket:
            raise StorageError("Invalid bucket")
        path = (self.root / bucket / object_key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise StorageError("Storage path escapes private root")
        return path

    def ensure_private_bucket(self, bucket, *, max_file_bytes, allowed_mime_types):
        path = self._path(bucket)
        existed = path.is_dir()
        path.mkdir(parents=True, exist_ok=True)
        return not existed

    def upload(self, bucket, object_key, content, mime_type):
        path = self._path(bucket, object_key)
        if not object_key or not content or len(content) > self.settings.storage_max_file_bytes:
            raise StorageError("File is empty or exceeds the configured size limit")
        temp = path.with_name(f".{uuid4()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # A complete file becomes visible atomically; existing evidence is immutable.
            with temp.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temp, path)
        except OSError as exc:
            raise StorageError("Private file could not be saved") from exc
        finally:
            temp.unlink(missing_ok=True)

    def download(self, bucket, object_key):
        path = self._path(bucket, object_key)
        try:
            return path.read_bytes(), mimetypes.guess_type(object_key)[0]
        except OSError as exc:
            raise StorageError("Private file is unavailable") from exc

    def delete(self, bucket, object_key):
        path = self._path(bucket, object_key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("Private file cleanup failed") from exc


def StorageService(settings=None, provider=None):
    settings = settings or get_settings()
    selected = provider or settings.storage_provider
    if selected == "LOCAL":
        return LocalStorageService(settings)
    if selected == "SUPABASE":
        return SupabaseStorageService(settings)
    raise StorageError("Unsupported storage provider")

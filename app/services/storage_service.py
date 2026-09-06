from __future__ import annotations

import httpx

from app.config.settings import Settings, get_settings


class StorageError(Exception):
    pass


class SupabaseStorageService:
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

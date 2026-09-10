"""Minimal Drive v3 client for app-created immutable backup artifacts."""

import hashlib
import json
import secrets
from pathlib import Path

import httpx

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


class GoogleDriveError(RuntimeError):
    pass


class GoogleDriveClient:
    def __init__(self, access_token: str) -> None:
        self.headers = {"Authorization": f"Bearer {access_token}"}

    @staticmethod
    def stable_key(kind: str, value: str) -> str:
        return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            response = httpx.request(method, url, headers=headers, timeout=60, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise GoogleDriveError("Google Drive request failed") from exc

    def _find(self, parent_id: str, key: str, mime_type: str | None = None) -> dict | None:
        clauses = [
            "trashed = false",
            f"'{parent_id}' in parents",
            f"appProperties has {{ key='bnc_key' and value='{key}' }}",
        ]
        if mime_type:
            clauses.append(f"mimeType = '{mime_type}'")
        response = self._request("GET", DRIVE_FILES_URL, params={
            "q": " and ".join(clauses), "spaces": "drive",
            "fields": "files(id,name,mimeType,size,md5Checksum,webViewLink)",
            "pageSize": 2,
        })
        files = response.json().get("files", [])
        if len(files) > 1:
            raise GoogleDriveError("Duplicate BNC backup object found")
        return files[0] if files else None

    def ensure_folder(self, name: str, parent_id: str, logical_path: str) -> dict:
        key = self.stable_key("folder", logical_path)
        existing = self._find(parent_id, key, FOLDER_MIME)
        if existing:
            return existing
        response = self._request("POST", DRIVE_FILES_URL, params={
            "fields": "id,name,mimeType,webViewLink"
        }, json={
            "name": name, "mimeType": FOLDER_MIME, "parents": [parent_id],
            "appProperties": {"bnc_key": key, "bnc_kind": "backup_folder"},
        })
        return response.json()

    def ensure_spreadsheet(self, name: str, parent_id: str, logical_path: str) -> dict:
        key = self.stable_key("sheet", logical_path)
        existing = self._find(parent_id, key, SHEET_MIME)
        if existing:
            return existing
        return self._request("POST", DRIVE_FILES_URL, params={
            "fields": "id,name,mimeType,webViewLink"
        }, json={
            "name": name, "mimeType": SHEET_MIME, "parents": [parent_id],
            "appProperties": {"bnc_key": key, "bnc_kind": "backup_sheet"},
        }).json()

    def ensure_file(self, source: Path, parent_id: str, logical_path: str, run_id: str) -> dict:
        content = source.read_bytes()
        md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
        key = self.stable_key("artifact", f"{run_id}:{logical_path}")
        existing = self._find(parent_id, key)
        if existing:
            if int(existing.get("size", -1)) != len(content) or existing.get("md5Checksum") != md5:
                raise GoogleDriveError("Existing Drive artifact does not match local backup")
            return existing
        metadata = {
            "name": source.name, "parents": [parent_id],
            "appProperties": {
                "bnc_key": key, "bnc_kind": "recovery_artifact", "bnc_run_id": run_id,
            },
        }
        if len(content) <= 5 * 1024 * 1024:
            uploaded = self._multipart_upload(metadata, content)
        else:
            uploaded = self._resumable_upload(metadata, content)
        if int(uploaded.get("size", -1)) != len(content) or uploaded.get("md5Checksum") != md5:
            raise GoogleDriveError("Uploaded Drive artifact failed integrity verification")
        return uploaded

    def _multipart_upload(self, metadata: dict, content: bytes) -> dict:
        boundary = f"bnc_{secrets.token_hex(16)}"
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        ).encode() + json.dumps(metadata, separators=(",", ":")).encode() + (
            f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self._request("POST", DRIVE_UPLOAD_URL, params={
            "uploadType": "multipart", "fields": "id,name,size,md5Checksum,webViewLink"
        }, headers={"Content-Type": f"multipart/related; boundary={boundary}"}, content=body).json()

    def _resumable_upload(self, metadata: dict, content: bytes) -> dict:
        start = self._request("POST", DRIVE_UPLOAD_URL, params={
            "uploadType": "resumable", "fields": "id,name,size,md5Checksum,webViewLink"
        }, headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "application/octet-stream",
            "X-Upload-Content-Length": str(len(content)),
        }, json=metadata)
        location = start.headers.get("Location")
        if not location:
            raise GoogleDriveError("Google Drive did not create an upload session")
        return self._request("PUT", location, headers={
            "Content-Type": "application/octet-stream", "Content-Length": str(len(content)),
        }, content=content).json()

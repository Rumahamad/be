import base64
import html
import re
from datetime import UTC, datetime

import httpx


class GmailClientError(RuntimeError):
    pass


class GmailClient:
    base_url = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, access_token: str) -> None:
        # Do not shadow the message-header parsing method below.
        self.request_headers = {"Authorization": f"Bearer {access_token}"}

    def _get(self, path: str, **params) -> dict:
        try:
            response = httpx.get(
                f"{self.base_url}/{path}", headers=self.request_headers, params=params, timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GmailClientError("Gmail request failed") from exc

    def list_message_ids(self, query: str, limit: int = 200) -> list[str]:
        ids, page_token = [], None
        while len(ids) < limit:
            payload = self._get(
                "messages", q=query, maxResults=min(100, limit - len(ids)),
                includeSpamTrash="false", **({"pageToken": page_token} if page_token else {}),
            )
            ids.extend(str(item["id"]) for item in payload.get("messages", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return ids

    def get_message(self, message_id: str) -> dict:
        return self._get(f"messages/{message_id}", format="full")

    @staticmethod
    def headers(message: dict) -> dict[str, str]:
        values: dict[str, list[str]] = {}
        for item in message.get("payload", {}).get("headers", []):
            name = str(item.get("name", "")).lower()
            if name:
                values.setdefault(name, []).append(str(item.get("value", "")))
        return {name: "\n".join(items) for name, items in values.items()}

    @classmethod
    def body_text(cls, message: dict) -> str:
        plain, rich = [], []

        def visit(part: dict) -> None:
            mime = str(part.get("mimeType", "")).lower()
            data = part.get("body", {}).get("data")
            if data:
                decoded = cls._decode(data)
                if mime == "text/plain":
                    plain.append(decoded)
                elif mime == "text/html":
                    rich.append(re.sub(r"<[^>]+>", " ", html.unescape(decoded)))
            for child in part.get("parts", []):
                visit(child)

        visit(message.get("payload", {}))
        return "\n".join(plain or rich)

    @staticmethod
    def received_at(message: dict) -> datetime:
        return datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=UTC)

    @staticmethod
    def _decode(value: str) -> str:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

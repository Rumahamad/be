import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, or_, update
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.admin_session_handoff import AdminSessionHandoff

HANDOFF_TTL = timedelta(seconds=60)


class AdminSessionHandoffConfigurationError(RuntimeError):
    pass


class AdminSessionHandoffService:
    @staticmethod
    def _cipher() -> Fernet:
        key = get_settings().admin_session_handoff_encryption_key
        if not key:
            raise AdminSessionHandoffConfigurationError(
                "Admin session handoff encryption is not configured"
            )
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise AdminSessionHandoffConfigurationError(
                "Admin session handoff encryption key is invalid"
            ) from exc

    @staticmethod
    def _digest(ticket: str) -> str:
        return hashlib.sha256(ticket.encode("ascii")).hexdigest()

    def issue(self, db: Session, user_id: UUID, refresh_token: str) -> tuple[str, datetime]:
        cipher = self._cipher()
        current_time = datetime.now(UTC)
        expires_at = current_time + HANDOFF_TTL
        ticket = secrets.token_urlsafe(32)
        db.execute(
            delete(AdminSessionHandoff).where(
                or_(
                    AdminSessionHandoff.expires_at <= current_time,
                    AdminSessionHandoff.consumed_at.is_not(None),
                )
            )
        )
        db.add(
            AdminSessionHandoff(
                ticket_digest=self._digest(ticket),
                user_id=user_id,
                encrypted_refresh_token=cipher.encrypt(
                    refresh_token.encode("utf-8")
                ).decode("ascii"),
                expires_at=expires_at,
            )
        )
        db.commit()
        return ticket, expires_at

    def consume(self, db: Session, ticket: str) -> tuple[UUID, str] | None:
        cipher = self._cipher()
        current_time = datetime.now(UTC)
        row = db.execute(
            update(AdminSessionHandoff)
            .where(
                AdminSessionHandoff.ticket_digest == self._digest(ticket),
                AdminSessionHandoff.consumed_at.is_(None),
                AdminSessionHandoff.expires_at > current_time,
            )
            .values(consumed_at=current_time)
            .returning(
                AdminSessionHandoff.user_id,
                AdminSessionHandoff.encrypted_refresh_token,
            )
        ).one_or_none()
        db.commit()
        if row is None:
            return None
        try:
            refresh_token = cipher.decrypt(row.encrypted_refresh_token.encode("ascii")).decode(
                "utf-8"
            )
        except (InvalidToken, UnicodeError) as exc:
            raise AdminSessionHandoffConfigurationError(
                "Stored admin session handoff cannot be decrypted"
            ) from exc
        return row.user_id, refresh_token

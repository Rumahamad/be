"""Owner Google OAuth for Drive backups; Gmail consent remains separate."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.backup import BackupOutbox, BackupRun, GoogleConnection, GoogleOAuthState
from app.models.identity import User
from app.schemas.backups import GoogleBackupStatusOutput
from app.services.audit_service import AuditService

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
SCOPES = ("openid", "email", DRIVE_FILE_SCOPE)
PURPOSE = "DRIVE_BACKUP"


class GoogleBackupOAuthError(RuntimeError):
    pass


class GoogleBackupOAuthService:
    def __init__(self) -> None:
        self.audit = AuditService()

    @staticmethod
    def _cipher() -> Fernet:
        settings = get_settings()
        if not settings.google_oauth_configured:
            raise GoogleBackupOAuthError("Google backup connection is not configured")
        try:
            return Fernet(settings.google_token_encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise GoogleBackupOAuthError("Google token encryption key is invalid") from exc

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    def start(self, db: Session, actor: User) -> tuple[str, datetime]:
        settings = get_settings()
        cipher = self._cipher()
        now = datetime.now(UTC)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        db.execute(delete(GoogleOAuthState).where(GoogleOAuthState.expires_at < now))
        expires_at = now + timedelta(minutes=10)
        db.add(GoogleOAuthState(
            state_digest=self._digest(state),
            encrypted_code_verifier=cipher.encrypt(verifier.encode("ascii")).decode("ascii"),
            purpose=PURPOSE,
            created_by=actor.id,
            expires_at=expires_at,
        ))
        db.commit()
        query = urlencode({
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"{GOOGLE_AUTHORIZE_URL}?{query}", expires_at

    def _consume_state(self, db: Session, state: str) -> tuple[UUID, str]:
        now = datetime.now(UTC)
        record = db.scalar(
            select(GoogleOAuthState)
            .where(
                GoogleOAuthState.state_digest == self._digest(state),
                GoogleOAuthState.purpose == PURPOSE,
                GoogleOAuthState.used_at.is_(None),
                GoogleOAuthState.expires_at > now,
            )
            .with_for_update()
        )
        if not record:
            raise GoogleBackupOAuthError("Google authorization request is invalid or expired")
        record.used_at = now
        try:
            verifier = self._cipher().decrypt(
                record.encrypted_code_verifier.encode("ascii")
            ).decode("ascii")
        except (InvalidToken, UnicodeError) as exc:
            db.rollback()
            raise GoogleBackupOAuthError("Google authorization state cannot be decrypted") from exc
        actor_id = record.created_by
        db.commit()  # consume before network I/O; a callback can never be replayed
        return actor_id, verifier

    def complete(self, db: Session, state: str, code: str) -> str:
        settings = get_settings()
        actor_id, verifier = self._consume_state(db, state)
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                token_response = client.post(GOOGLE_TOKEN_URL, data={
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "code": code,
                    "code_verifier": verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.google_oauth_redirect_uri,
                })
                token_response.raise_for_status()
                tokens = token_response.json()
                access_token = tokens.get("access_token")
                refresh_token = tokens.get("refresh_token")
                if not access_token or not refresh_token:
                    raise GoogleBackupOAuthError("Google did not return offline access")
                user_response = client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                user_response.raise_for_status()
                identity = user_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleBackupOAuthError("Google authorization could not be completed") from exc
        email = str(identity.get("email", "")).strip().lower()
        subject = str(identity.get("sub", "")).strip()
        if not email or not subject or identity.get("email_verified") is not True:
            raise GoogleBackupOAuthError("Google account email is not verified")
        if settings.google_owner_email and email != settings.google_owner_email.strip().lower():
            raise GoogleBackupOAuthError("This is not the configured backup owner account")
        scopes = sorted(set(str(tokens.get("scope", "")).split()))
        if DRIVE_FILE_SCOPE not in scopes:
            raise GoogleBackupOAuthError("Google Drive file permission was not granted")
        encrypted = self._cipher().encrypt(refresh_token.encode("utf-8")).decode("ascii")
        connection = db.scalar(
            select(GoogleConnection).where(GoogleConnection.purpose == PURPOSE).with_for_update()
        )
        if not connection:
            connection = GoogleConnection(
                purpose=PURPOSE,
                account_subject=subject,
                account_email=email,
                encrypted_refresh_token=encrypted,
                granted_scopes=scopes,
                connected_by=actor_id,
            )
            db.add(connection)
            db.flush()
        else:
            connection.account_subject = subject
            connection.account_email = email
            connection.encrypted_refresh_token = encrypted
            connection.granted_scopes = scopes
            connection.status = "ACTIVE"
            connection.connected_by = actor_id
            connection.last_verified_at = datetime.now(UTC)
            connection.last_error_code = None
        self.audit.record(
            db,
            actor_user_id=actor_id,
            action="backup.google_connected",
            entity_type="google_connections",
            entity_id=connection.id,
            after_data={"purpose": PURPOSE, "account_email": email, "scopes": scopes},
        )
        db.commit()
        return email

    @staticmethod
    def status(db: Session) -> GoogleBackupStatusOutput:
        settings = get_settings()
        if not settings.google_oauth_configured:
            return GoogleBackupStatusOutput(configured=False, connected=False)
        connection = db.scalar(
            select(GoogleConnection).where(GoogleConnection.purpose == PURPOSE)
        )
        latest = db.scalar(select(BackupRun).order_by(BackupRun.created_at.desc()).limit(1))
        latest_successful = db.scalar(
            select(BackupRun).where(
                BackupRun.status == "SUCCEEDED", BackupRun.source_cutoff.is_not(None)
            ).order_by(BackupRun.source_cutoff.desc()).limit(1)
        )
        pending_sheet_changes = db.scalar(select(func.count()).select_from(BackupOutbox).where(
            BackupOutbox.status.in_(("PENDING", "PROCESSING", "FAILED")),
            BackupOutbox.attempt_count < 5,
        )) or 0
        last_sheet_sync_at = db.scalar(select(func.max(BackupOutbox.processed_at)))
        return GoogleBackupStatusOutput(
            configured=settings.google_oauth_configured,
            connected=bool(connection and connection.status == "ACTIVE"),
            account_email=connection.account_email if connection else None,
            status=connection.status if connection else None,
            granted_scopes=connection.granted_scopes if connection else [],
            last_verified_at=connection.last_verified_at if connection else None,
            latest_run_status=latest.status if latest else None,
            latest_run_started_at=latest.started_at if latest else None,
            latest_run_completed_at=latest.completed_at if latest else None,
            latest_successful_cutoff=latest_successful.source_cutoff if latest_successful else None,
            pending_sheet_changes=pending_sheet_changes,
            last_sheet_sync_at=last_sheet_sync_at,
            latest_run_error_code=latest.error_code if latest else None,
            root_web_link=connection.root_web_link if connection else None,
        )

    def decrypt_refresh_token(self, connection: GoogleConnection) -> str:
        try:
            return self._cipher().decrypt(
                connection.encrypted_refresh_token.encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise GoogleBackupOAuthError("Stored Google connection cannot be decrypted") from exc

    def access_token(self, connection: GoogleConnection) -> str:
        settings = get_settings()
        try:
            response = httpx.post(GOOGLE_TOKEN_URL, data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "refresh_token": self.decrypt_refresh_token(connection),
                "grant_type": "refresh_token",
            }, timeout=20)
            response.raise_for_status()
            token = response.json().get("access_token")
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleBackupOAuthError("Google access token refresh failed") from exc
        if not token:
            raise GoogleBackupOAuthError("Google access token refresh failed")
        return str(token)

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.backup import GoogleConnection, GoogleOAuthState
from app.models.identity import User
from app.services.audit_service import AuditService
from app.services.google_backup_oauth_service import (
    GOOGLE_AUTHORIZE_URL, GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL, GoogleBackupOAuthError,
)

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
PURPOSE = "HDFC_GMAIL"
SCOPES = ("openid", "email", GMAIL_SCOPE)


class GmailVerificationOAuthService:
    def __init__(self) -> None:
        self.audit = AuditService()

    @staticmethod
    def _cipher() -> Fernet:
        settings = get_settings()
        try:
            return Fernet(settings.google_token_encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise GoogleBackupOAuthError("Google token encryption key is invalid") from exc

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    def start(self, db: Session, actor: User) -> tuple[str, datetime]:
        settings = get_settings()
        if not settings.gmail_verification_configured:
            raise GoogleBackupOAuthError("Gmail verification configuration is incomplete")
        cipher = self._cipher()
        now = datetime.now(UTC)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
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
            "redirect_uri": settings.gmail_oauth_redirect_uri,
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

    def complete(self, db: Session, state: str, code: str) -> str:
        settings = get_settings()
        actor_id, verifier = self._consume_state(db, state)
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                response = client.post(GOOGLE_TOKEN_URL, data={
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "code": code,
                    "code_verifier": verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.gmail_oauth_redirect_uri,
                })
                response.raise_for_status()
                tokens = response.json()
                access_token, refresh_token = tokens.get("access_token"), tokens.get("refresh_token")
                if not access_token or not refresh_token:
                    raise GoogleBackupOAuthError("Google did not return offline Gmail access")
                identity_response = client.get(
                    GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"},
                )
                identity_response.raise_for_status()
                identity = identity_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleBackupOAuthError("Gmail authorization could not be completed") from exc
        email = str(identity.get("email", "")).strip().lower()
        subject = str(identity.get("sub", "")).strip()
        if not email or not subject or identity.get("email_verified") is not True:
            raise GoogleBackupOAuthError("Google account email is not verified")
        expected_email = (
            settings.gmail_verification_account_email
            or settings.gmail_owner_email
            or settings.google_owner_email
        ).strip().lower()
        if expected_email and email != expected_email:
            raise GoogleBackupOAuthError("This is not the configured Gmail verification account")
        scopes = sorted(set(str(tokens.get("scope", "")).split()))
        if GMAIL_SCOPE not in scopes:
            raise GoogleBackupOAuthError("Gmail read-only permission was not granted")
        encrypted = self._cipher().encrypt(refresh_token.encode("utf-8")).decode("ascii")
        connection = db.scalar(select(GoogleConnection).where(
            GoogleConnection.purpose == PURPOSE
        ).with_for_update())
        if not connection:
            connection = GoogleConnection(
                purpose=PURPOSE, account_subject=subject, account_email=email,
                encrypted_refresh_token=encrypted, granted_scopes=scopes, connected_by=actor_id,
            )
            db.add(connection); db.flush()
        else:
            connection.account_subject = subject
            connection.account_email = email
            connection.encrypted_refresh_token = encrypted
            connection.granted_scopes = scopes
            connection.connected_by = actor_id
            connection.status = "ACTIVE"
            connection.last_verified_at = datetime.now(UTC)
            connection.last_error_code = None
        self.audit.record(
            db, actor_user_id=actor_id, action="verification.gmail_connected",
            entity_type="google_connections", entity_id=connection.id,
            after_data={"purpose": PURPOSE, "account_email": email, "scopes": scopes},
        )
        db.commit()
        return email

    def _consume_state(self, db: Session, state: str) -> tuple[UUID, str]:
        now = datetime.now(UTC)
        record = db.scalar(select(GoogleOAuthState).where(
            GoogleOAuthState.state_digest == self._digest(state),
            GoogleOAuthState.purpose == PURPOSE,
            GoogleOAuthState.used_at.is_(None),
            GoogleOAuthState.expires_at > now,
        ).with_for_update())
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
        db.commit()
        return actor_id, verifier

    def access_token(self, connection: GoogleConnection) -> str:
        settings = get_settings()
        try:
            refresh_token = self._cipher().decrypt(
                connection.encrypted_refresh_token.encode("ascii")
            ).decode("utf-8")
            response = httpx.post(GOOGLE_TOKEN_URL, data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }, timeout=20)
            response.raise_for_status()
            token = response.json().get("access_token")
        except (InvalidToken, UnicodeError, httpx.HTTPError, ValueError) as exc:
            raise GoogleBackupOAuthError("Gmail access token refresh failed") from exc
        if not token:
            raise GoogleBackupOAuthError("Gmail access token refresh failed")
        return str(token)

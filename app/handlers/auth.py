from dataclasses import replace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import access_token_user
from app.config.settings import get_settings
from app.models.identity import User
from app.schemas.auth import (
    ChangePasswordInput,
    ForgotPasswordInput,
    LoginInput,
    OAuthSessionInput,
    RecoverPasswordInput,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthProviderError, AuthService, AuthSession


class AuthHandler:
    def __init__(self) -> None:
        self.auth = AuthService()
        self.audit = AuditService()

    def login(self, db: Session, payload: LoginInput) -> AuthSession:
        identifier = payload.identifier.strip()
        if "@" not in identifier:
            member = db.scalar(select(User).where(User.mobile == identifier))
            if member:
                identifier = member.email
        try:
            session = self.auth.login(identifier, payload.password)
        except AuthProviderError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        user = access_token_user(session.access_token, db)
        return replace(session, password_setup_required=user.password_setup_required)

    def refresh(self, db: Session, refresh_token: str) -> AuthSession:
        try:
            session = self.auth.refresh(refresh_token)
        except AuthProviderError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        user = access_token_user(session.access_token, db)
        return replace(session, password_setup_required=user.password_setup_required)

    def accept_oauth_session(self, db: Session, payload: OAuthSessionInput) -> AuthSession:
        user = access_token_user(payload.access_token, db)
        return AuthSession(
            access_token=payload.access_token,
            refresh_token=payload.refresh_token,
            expires_in=payload.expires_in,
            password_setup_required=user.password_setup_required,
        )

    def set_password(self, db: Session, user: User, access_token: str, password: str) -> None:
        try:
            self.auth.update_password(access_token, password)
        except AuthProviderError as exc:
            status_code = 503 if str(exc) == "Authentication service is unavailable" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        user.password_setup_required = False
        db.commit()

    def change_password(
        self,
        db: Session,
        user: User,
        access_token: str,
        payload: ChangePasswordInput,
    ) -> None:
        try:
            self.auth.login(user.email, payload.current_password)
            self.auth.update_password(access_token, payload.new_password)
        except AuthProviderError as exc:
            status_code = 503 if str(exc) == "Authentication service is unavailable" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        self.audit.record(
            db,
            actor_user_id=user.id,
            action="user.password_changed",
            entity_type="user",
            entity_id=user.id,
        )
        db.commit()

    def request_password_reset(self, db: Session, payload: ForgotPasswordInput) -> None:
        email = payload.email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        # Always return the same response so this endpoint cannot enumerate accounts.
        if not user or user.auth_user_id is None:
            return
        redirect_to = f"{get_settings().frontend_url.rstrip('/')}/auth/reset-password"
        try:
            self.auth.request_password_reset(email, redirect_to)
        except AuthProviderError as exc:
            status_code = 503 if str(exc) == "Authentication service is unavailable" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    def recover_password(self, db: Session, payload: RecoverPasswordInput) -> None:
        try:
            session = self.auth.verify_recovery_token(payload.token_hash)
            user = access_token_user(session.access_token, db)
            self.auth.update_password(session.access_token, payload.password)
        except AuthProviderError as exc:
            status_code = 503 if str(exc) == "Authentication service is unavailable" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        user.password_setup_required = False
        db.commit()

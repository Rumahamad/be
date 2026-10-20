"""Identity administration with a local default and explicit migration fallback."""

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.config.settings import get_settings
from app.db.session import SessionLocal
from app.models.local_auth import LocalIdentity
from app.services.auth_service import AuthProviderError
from app.services.local_auth_service import LocalAuthService, hash_password
from app.services.supabase_admin_service import (
    CreatedAuthUser,
    SupabaseAdminService,
)
from app.services.supabase_admin_service import (
    SupabaseAdminError as AuthAdminError,
)


class LocalAuthAdminService:
    def __init__(self, settings=None, session_factory=None):
        self.settings = settings or get_settings()
        self.session_factory = session_factory or SessionLocal
        self.auth = LocalAuthService(self.settings, self.session_factory)

    def create_user(self, email, password, display_name):
        try:
            identity = LocalIdentity(id=uuid4(), email=email.lower(),
                                     password_hash=hash_password(password))
            with self.session_factory() as db, db.begin():
                db.add(identity)
            return CreatedAuthUser(identity.id, identity.email)
        except IntegrityError as exc:
            raise AuthAdminError("An identity with this email already exists") from exc

    def invite_user(self, email, display_name, redirect_to):
        identity = LocalIdentity(id=uuid4(), email=email.lower())
        try:
            with self.session_factory() as db, db.begin():
                db.add(identity)
        except IntegrityError as exc:
            raise AuthAdminError("An identity with this email already exists") from exc
        try:
            self.auth.send_link(identity.id, identity.email, redirect_to)
        except AuthProviderError as exc:
            self.delete_user(identity.id)
            raise AuthAdminError(str(exc)) from exc
        return CreatedAuthUser(identity.id, identity.email)

    def delete_user(self, auth_user_id):
        with self.session_factory() as db, db.begin():
            identity = db.get(LocalIdentity, auth_user_id)
            if identity:
                db.delete(identity)

    def send_password_reset(self, email, redirect_to):
        try:
            self.auth.request_password_reset(email, redirect_to)
        except AuthProviderError as exc:
            raise AuthAdminError(str(exc)) from exc


def AuthAdminService(settings=None):
    settings = settings or get_settings()
    if settings.auth_provider == "supabase":
        return SupabaseAdminService(settings)
    return LocalAuthAdminService(settings)

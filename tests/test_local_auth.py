"""Security integration tests against an explicitly named disposable local database."""
import os
from datetime import timedelta
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config.settings import Settings
from app.db.session import Base
from app.models import core  # noqa: F401
from app.models.enums import UserStatus
from app.models.identity import Role, User
from app.models.local_auth import LocalIdentity, LocalToken
from app.services.auth_service import AuthProviderError
from app.services.local_auth_service import (
    LocalAuthService,
    hash_password,
    now,
    token_digest,
)


@pytest.fixture(scope="module")
def factory():
    url = os.environ.get("BNC_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set BNC_TEST_DATABASE_URL to a disposable localhost PostgreSQL database")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.startswith("bnc_test_")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def auth(factory):
    with factory() as db, db.begin():
        db.execute(text("TRUNCATE users, roles, local_auth_identities CASCADE"))
        role = Role(id=uuid4(), code="MEMBER", name="Member", is_system=True, is_protected=False)
        identity = LocalIdentity(id=uuid4(), email="member@example.test", password_hash=hash_password("original-password"))
        db.add_all([role, identity]); db.flush()
        db.add(User(auth_user_id=identity.id, member_code="TEST-1", first_name="Test",
            display_name="Test", email=identity.email, role_id=role.id,
            status=UserStatus.ACTIVE, password_setup_required=True))
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://unused",
        local_auth_secret="testing-only-" + "a" * 40)
    return LocalAuthService(settings, factory)


def test_login_refresh_replay_revokes_session(auth):
    session = auth.login("member@example.test", "original-password")
    auth.validate(session.access_token)
    rotated = auth.refresh(session.refresh_token)
    with pytest.raises(AuthProviderError):
        auth.refresh(session.refresh_token)
    with pytest.raises(AuthProviderError):
        auth.validate(rotated.access_token)


def test_logout_revokes_access_and_refresh(auth):
    session = auth.login("member@example.test", "original-password")
    auth.logout(session.access_token)
    with pytest.raises(AuthProviderError):
        auth.validate(session.access_token)
    with pytest.raises(AuthProviderError):
        auth.refresh(session.refresh_token)


def test_recovery_one_use_and_revokes_all_sessions(auth, factory):
    session = auth.login("member@example.test", "original-password")
    with factory() as db, db.begin():
        identity = db.scalar(select(LocalIdentity))
        db.add(LocalToken(digest=token_digest("one-use-token"), purpose="recovery",
            identity_id=identity.id, expires_at=now() + timedelta(minutes=5)))
    auth.recover_password("one-use-token", "replacement-password")
    auth.login("member@example.test", "replacement-password")
    with pytest.raises(AuthProviderError):
        auth.recover_password("one-use-token", "another-password")
    with pytest.raises(AuthProviderError):
        auth.validate(session.access_token)
    with factory() as db:
        assert db.scalar(select(User)).password_setup_required is False


def test_expired_recovery_cannot_change_password(auth, factory):
    with factory() as db, db.begin():
        identity = db.scalar(select(LocalIdentity))
        db.add(LocalToken(digest=token_digest("expired"), purpose="recovery",
            identity_id=identity.id, expires_at=now() - timedelta(minutes=1)))
    with pytest.raises(AuthProviderError):
        auth.recover_password("expired", "replacement-password")
    auth.login("member@example.test", "original-password")


def test_imported_bcrypt_password_is_preserved_and_upgraded(auth, factory):
    with factory() as db, db.begin():
        db.scalar(select(LocalIdentity)).password_hash = bcrypt.hashpw(b"old-password", bcrypt.gensalt()).decode()
    auth.login("member@example.test", "old-password")
    with factory() as db:
        assert db.scalar(select(LocalIdentity)).password_hash.startswith("scrypt$")


def test_wrong_password_and_blocked_user_cannot_login(auth, factory):
    with pytest.raises(AuthProviderError):
        auth.login("member@example.test", "incorrect-password")
    with factory() as db, db.begin():
        assert db.scalar(select(LocalIdentity)).failed_attempts == 1
        db.scalar(select(User)).status = UserStatus.BLOCKED
    with pytest.raises(AuthProviderError):
        auth.login("member@example.test", "original-password")


def test_unknown_user_cannot_login(auth):
    with pytest.raises(AuthProviderError):
        auth.login("missing@example.test", "original-password")


def test_password_change_preserves_current_session_revokes_other(auth):
    first = auth.login("member@example.test", "original-password")
    second = auth.login("member@example.test", "original-password")
    auth.update_password(first.access_token, "replacement-password")
    auth.validate(first.access_token)
    with pytest.raises(AuthProviderError):
        auth.validate(second.access_token)


def test_recovery_issues_no_token_without_email_configuration(auth, factory):
    with pytest.raises(AuthProviderError, match="SMTP"):
        auth.request_password_reset("member@example.test", "https://example.test/auth/reset-password")
    with factory() as db:
        assert db.scalar(select(LocalToken).where(LocalToken.purpose == "recovery")) is None


def test_google_state_is_expiring_and_one_use(auth, factory):
    auth.settings.google_oauth_client_id = "test-client"
    auth.settings.google_oauth_client_secret = "test-secret"
    url, state = auth.begin_google("https://example.test/")
    assert "code_challenge_method=S256" in url
    with factory() as db, db.begin():
        db.get(LocalToken, token_digest(state)).expires_at = now() - timedelta(seconds=1)
    with pytest.raises(AuthProviderError, match="expired"):
        auth.finish_google("unused-code", state)

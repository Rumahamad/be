from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api import dependencies
from app.api.v1 import auth
from app.models.admin_session_handoff import AdminSessionHandoff
from app.models.enums import UserStatus
from app.schemas.auth import (
    MobileAdminSessionExchangeInput,
    MobileAdminSessionInput,
    MobileAdminSessionTicketOutput,
)
from app.services.admin_session_handoff_service import AdminSessionHandoffService
from app.services.auth_service import AuthSession


def admin_user():
    return SimpleNamespace(
        id=uuid4(),
        role_id=uuid4(),
        status=UserStatus.ACTIVE,
    )


def test_admin_handoff_mint_requires_authentication(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(auth_bypass_enabled=False),
    )

    with pytest.raises(HTTPException) as error:
        dependencies.current_user(credentials=None, x_bnc_user_id=None, db=object())

    assert error.value.status_code == 401


def test_non_admin_cannot_mint_handoff():
    db = SimpleNamespace(scalar=lambda statement: "MEMBER")

    with pytest.raises(HTTPException) as error:
        auth.mobile_admin_session(
            MobileAdminSessionInput(refresh_token="refresh"),
            Response(),
            db,
            admin_user(),
        )

    assert error.value.status_code == 403


def test_admin_mint_returns_only_ticket_and_expiry(monkeypatch):
    expires_at = datetime.now(UTC) + timedelta(seconds=60)
    user = admin_user()
    db = SimpleNamespace(scalar=lambda statement: "ADMIN")
    monkeypatch.setattr(auth, "user_has_permission", lambda *args: True)
    monkeypatch.setattr(
        auth.admin_session_handoffs,
        "issue",
        lambda *args: ("a" * 43, expires_at),
    )
    response = Response()

    result = auth.mobile_admin_session(
        MobileAdminSessionInput(refresh_token="refresh"),
        response,
        db,
        user,
    )

    assert result == MobileAdminSessionTicketOutput(ticket="a" * 43, expires_at=expires_at)
    assert set(result.model_dump()) == {"ticket", "expires_at"}
    assert response.headers["cache-control"] == "no-store"


def test_exchange_rejects_client_redirect_fields():
    with pytest.raises(ValidationError):
        MobileAdminSessionExchangeInput(ticket="a" * 43, redirect_url="https://example.test")


def test_exchange_issues_web_session_and_refresh_cookie(monkeypatch):
    user = admin_user()
    db = SimpleNamespace(
        get=lambda model, user_id: user,
        scalar=lambda statement: "ADMIN",
    )
    monkeypatch.setattr(auth, "user_has_permission", lambda *args: True)
    monkeypatch.setattr(auth, "access_token_user", lambda *args: user)
    monkeypatch.setattr(
        auth.admin_session_handoffs,
        "consume",
        lambda *args: (user.id, "native-refresh"),
    )
    monkeypatch.setattr(
        auth.handler,
        "refresh",
        lambda *args: AuthSession("web-access", "rotated-refresh", 3600),
    )
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            auth_refresh_cookie_name="bnc_refresh_token",
            auth_refresh_cookie_max_age=3600,
            auth_cookie_secure=True,
            auth_cookie_samesite="lax",
        ),
    )
    response = Response()

    result = auth.exchange_mobile_admin_session(
        MobileAdminSessionExchangeInput(ticket="a" * 43),
        response,
        db,
    )

    assert result.access_token == "web-access"
    assert result.expires_in == 3600
    assert "rotated-refresh" not in result.model_dump_json()
    assert "bnc_refresh_token=rotated-refresh" in response.headers["set-cookie"]
    assert "path=/api/v1/auth" in response.headers["set-cookie"].lower()
    assert "domain=" not in response.headers["set-cookie"].lower()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("state", ["expired", "already consumed"])
def test_expired_or_replayed_ticket_cannot_exchange(monkeypatch, state):
    del state
    monkeypatch.setattr(auth.admin_session_handoffs, "consume", lambda *args: None)

    with pytest.raises(HTTPException) as error:
        auth.exchange_mobile_admin_session(
            MobileAdminSessionExchangeInput(ticket="a" * 43),
            Response(),
            object(),
        )

    assert error.value.status_code == 401


def test_deactivated_user_cannot_exchange(monkeypatch):
    user = admin_user()
    user.status = UserStatus.BLOCKED
    db = SimpleNamespace(get=lambda model, user_id: user)
    monkeypatch.setattr(
        auth.admin_session_handoffs,
        "consume",
        lambda *args: (user.id, "native-refresh"),
    )
    monkeypatch.setattr(
        auth.handler,
        "refresh",
        lambda *args: pytest.fail("must not refresh"),
    )

    with pytest.raises(HTTPException) as error:
        auth.exchange_mobile_admin_session(
            MobileAdminSessionExchangeInput(ticket="a" * 43),
            Response(),
            db,
        )

    assert error.value.status_code == 403


def test_exchange_rechecks_admin_privileges_after_refresh(monkeypatch):
    user = admin_user()
    role_codes = iter(["ADMIN", "MEMBER"])
    permission_checks = iter([True, False])
    db = SimpleNamespace(
        get=lambda model, user_id: user,
        scalar=lambda statement: next(role_codes),
    )
    monkeypatch.setattr(auth, "user_has_permission", lambda *args: next(permission_checks))
    monkeypatch.setattr(auth, "access_token_user", lambda *args: user)
    monkeypatch.setattr(
        auth.admin_session_handoffs,
        "consume",
        lambda *args: (user.id, "native-refresh"),
    )
    monkeypatch.setattr(
        auth.handler,
        "refresh",
        lambda *args: AuthSession("web-access", "rotated-refresh", 3600),
    )

    with pytest.raises(HTTPException) as error:
        auth.exchange_mobile_admin_session(
            MobileAdminSessionExchangeInput(ticket="a" * 43),
            Response(),
            db,
        )

    assert error.value.status_code == 403


def test_consume_is_atomic_and_enforces_expiry_and_replay(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        "app.services.admin_session_handoff_service.get_settings",
        lambda: SimpleNamespace(admin_session_handoff_encryption_key=key),
    )
    handoffs = AdminSessionHandoffService()
    user_id = uuid4()
    engine = create_engine("sqlite://")
    try:
        AdminSessionHandoff.__table__.create(engine)
        with Session(engine) as db:
            expired_ticket, _ = handoffs.issue(db, user_id, "expired-refresh")
        with Session(engine) as db:
            expired = db.scalar(select(AdminSessionHandoff))
            assert expired.ticket_digest != expired_ticket
            assert expired.encrypted_refresh_token != "expired-refresh"
            expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
            assert handoffs.consume(db, expired_ticket) is None

        with Session(engine) as db:
            ticket, _ = handoffs.issue(db, user_id, "native-refresh")
            assert handoffs.consume(db, ticket) == (user_id, "native-refresh")
            assert handoffs.consume(db, ticket) is None
    finally:
        engine.dispose()

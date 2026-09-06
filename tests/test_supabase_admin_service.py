from types import SimpleNamespace
from uuid import UUID

import httpx

from app.services.supabase_admin_service import SupabaseAdminError, SupabaseAdminService


def test_create_user_uses_service_role_and_confirms_email(monkeypatch) -> None:
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_admin_api_key="sb_secret_service-key",
    )

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://example.supabase.co/auth/v1/admin/users"
        assert kwargs["headers"] == {"apikey": "sb_secret_service-key"}
        assert kwargs["json"]["email_confirm"] is True
        return httpx.Response(
            200,
            json={"id": "aaf3a4b7-ff16-46af-9471-b58707901710", "email": "admin@bnc.test"},
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    user = SupabaseAdminService(settings=settings).create_user(
        "admin@bnc.test", "password", "BNC Admin"
    )
    assert user.id == UUID("aaf3a4b7-ff16-46af-9471-b58707901710")


def test_invite_user_sends_redirect_and_metadata(monkeypatch) -> None:
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_admin_api_key="sb_secret_service-key",
    )

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://example.supabase.co/auth/v1/invite"
        assert kwargs["params"] == {"redirect_to": "https://bnc.test"}
        assert kwargs["json"]["data"] == {"display_name": "New Member"}
        return httpx.Response(
            200,
            json={"id": "8387ed6a-c470-40a4-81b1-777bf6d49750", "email": "member@bnc.test"},
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    user = SupabaseAdminService(settings=settings).invite_user(
        "member@bnc.test", "New Member", "https://bnc.test"
    )
    assert user.email == "member@bnc.test"


def test_admin_error_includes_supabase_msg_and_code(monkeypatch) -> None:
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_admin_api_key="sb_secret_service-key",
    )

    def fake_request(method, url, **kwargs):
        return httpx.Response(
            422,
            json={"msg": "A user with this email already exists", "error_code": "email_exists"},
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    try:
        SupabaseAdminService(settings=settings).invite_user(
            "member@bnc.test", "New Member", "https://bnc.test"
        )
    except SupabaseAdminError as exc:
        assert exc.status_code == 422
        assert exc.error_code == "email_exists"
        assert str(exc) == "A user with this email already exists (email_exists)"
    else:
        raise AssertionError("Expected SupabaseAdminError")


def test_password_reset_uses_recovery_endpoint(monkeypatch) -> None:
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_admin_api_key="sb_secret_service-key",
    )

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://example.supabase.co/auth/v1/recover"
        assert kwargs["params"] == {"redirect_to": "https://bnc.test"}
        assert kwargs["json"] == {"email": "member@bnc.test"}
        return httpx.Response(200, json={})

    monkeypatch.setattr(httpx, "request", fake_request)
    SupabaseAdminService(settings=settings).send_password_reset(
        "member@bnc.test", "https://bnc.test"
    )

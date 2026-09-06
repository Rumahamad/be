from types import SimpleNamespace

import httpx
import pytest

from app.services.auth_service import AuthProviderError, AuthService


def service() -> AuthService:
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_public_api_key="public-key",
    )
    return AuthService(settings=settings)


def test_password_login_uses_supabase_token_endpoint(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        assert url == "https://example.supabase.co/auth/v1/token"
        assert kwargs["params"] == {"grant_type": "password"}
        assert kwargs["json"] == {"email": "member@example.com", "password": "secret"}
        return httpx.Response(
            200,
            json={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    session = service().login("member@example.com", "secret")
    assert session.access_token == "access"
    assert session.refresh_token == "refresh"


def test_invalid_credentials_are_not_leaked(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(400))
    with pytest.raises(AuthProviderError, match="Invalid login credentials"):
        service().login("member@example.com", "wrong")


def test_update_password_uses_authenticated_user_endpoint(monkeypatch) -> None:
    def fake_put(url, **kwargs):
        assert url == "https://example.supabase.co/auth/v1/user"
        assert kwargs["headers"] == {
            "apikey": "public-key",
            "Authorization": "Bearer access-token",
            "Content-Type": "application/json",
        }
        assert kwargs["json"] == {"password": "new-password"}
        return httpx.Response(200, json={"user": {"id": "user-id"}})

    monkeypatch.setattr(httpx, "put", fake_put)
    service().update_password("access-token", "new-password")


def test_update_password_surfaces_provider_message(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "put",
        lambda *args, **kwargs: httpx.Response(422, json={"msg": "Password is too weak"}),
    )
    with pytest.raises(AuthProviderError, match="Password is too weak"):
        service().update_password("access-token", "weak")

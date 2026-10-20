from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.api.v1 import auth
from app.schemas.auth import MobileExchangeInput
from app.services.auth_service import AuthSession, SupabaseAuthService


def test_pkce_exchange_uses_verifier(monkeypatch):
    def post(url, **kwargs):
        assert kwargs["params"] == {"grant_type": "pkce"}
        assert kwargs["json"] == {"auth_code": "code", "code_verifier": "v" * 43}
        return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600})
    monkeypatch.setattr(httpx, "post", post)
    service = SupabaseAuthService(SimpleNamespace(supabase_url="https://example.supabase.co", supabase_public_api_key="public"))
    assert service.exchange_pkce("code", "v" * 43).access_token == "access"


def test_native_redirect_is_fixed_and_uses_s256(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(auth_provider="supabase", frontend_url="https://bnc-ui.vercel.app"))
    monkeypatch.setattr(auth.handler.auth, "google_authorize_url", lambda target: "https://example.supabase.co/authorize?redirect_to=" + target)
    response = auth.mobile_google("a" * 43)
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["redirect_to"] == ["https://bnc-ui.vercel.app/auth/android/callback"]
    assert query["code_challenge_method"] == ["s256"]


def test_exchange_does_not_bypass_membership(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(auth_provider="supabase"))
    monkeypatch.setattr(auth.handler.auth, "exchange_pkce", lambda *args: AuthSession("access", "refresh", 3600))
    def reject(*args):
        raise HTTPException(status_code=403, detail="Member not approved")
    monkeypatch.setattr(auth.handler, "accept_oauth_session", reject)
    response = Response()
    with pytest.raises(HTTPException) as error:
        auth.mobile_exchange(MobileExchangeInput(auth_code="code", code_verifier="v" * 43), response, object())
    assert error.value.status_code == 403
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("verifier", ["short", "v" * 129, "!" * 43])
def test_invalid_verifiers_rejected(verifier):
    with pytest.raises(ValidationError):
        MobileExchangeInput(auth_code="code", code_verifier=verifier)

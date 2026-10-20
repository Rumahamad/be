from functools import lru_cache

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient

from app.config.settings import get_settings


@lru_cache
def jwks_client() -> PyJWKClient:
    return PyJWKClient(get_settings().supabase_jwks_url, cache_keys=True, lifespan=3600)


def verify_access_token(token: str) -> dict:
    settings = get_settings()
    if settings.auth_provider == "local":
        from app.services.auth_service import AuthProviderError
        from app.services.local_auth_service import LocalAuthService
        try:
            return LocalAuthService(settings).validate(token)
        except AuthProviderError as exc:
            raise HTTPException(status_code=401, detail=str(exc),
                                headers={"WWW-Authenticate": "Bearer"}) from exc
    try:
        signing_key = jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "EdDSA"],
            audience=settings.supabase_jwt_audience,
            issuer=settings.supabase_jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

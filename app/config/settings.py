from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    supabase_url: str
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "bnc-payment-files"
    storage_max_file_bytes: int = 5 * 1024 * 1024
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    auth_bypass_enabled: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "https://bnc.pp.ua", "https://www.bnc.pp.ua"]
    frontend_url: str = "https://bnc.pp.ua"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_refresh_cookie_name: str = "bnc_refresh_token"
    auth_refresh_cookie_max_age: int = 60 * 60 * 24 * 30
    email_provider: Literal["disabled", "smtp"] = "disabled"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "BNC"
    smtp_reply_to: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 30
    email_app_name: str = "BNC"
    notification_max_attempts: int = 5

    # Web Push / VAPID
    vapid_public_key: str = ""
    vapid_private_key_pem: str = ""
    vapid_subject: str = "mailto:admin@bnc.pp.ua"

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key_pem)

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_jwt_issuer.rstrip('/')}/.well-known/jwks.json"

    @property
    def supabase_public_api_key(self) -> str:
        return self.supabase_publishable_key or self.supabase_anon_key

    @property
    def supabase_admin_api_key(self) -> str:
        return self.supabase_secret_key or self.supabase_service_role_key

    @property
    def email_enabled(self) -> bool:
        return self.email_provider != "disabled"


@lru_cache
def get_settings() -> Settings:
    return Settings()

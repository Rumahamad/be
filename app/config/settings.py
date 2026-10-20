from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    auth_provider: Literal["local", "supabase"] = "local"
    storage_provider: Literal["LOCAL", "SUPABASE"] = "LOCAL"
    local_storage_root: str = ".local/storage"
    storage_bucket: str = "bnc-payment-files"
    local_auth_secret: str = ""
    local_auth_issuer: str = "bnc-local"
    local_auth_access_seconds: int = 900
    local_auth_link_seconds: int = 3600
    backup_encryption_key: str = ""
    admin_session_handoff_encryption_key: str = ""
    postgres_bin: str = ".local/postgresql/pgsql/bin"
    google_login_redirect_uri: str = "http://127.0.0.1:5173/api/v1/auth/google/callback"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "bnc-payment-files"
    storage_max_file_bytes: int = 5 * 1024 * 1024
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    auth_bypass_enabled: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "https://bnc.pp.ua", "https://www.bnc.pp.ua", "https://bamarrahnaujawancommittee.pp.ua"]
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

    # Owner-only Google integration. Secrets and refresh tokens never reach the UI.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""
    google_token_encryption_key: str = ""
    google_owner_email: str = ""

    # Gmail payment sources remain shadow-only until real message headers are verified.
    payment_auto_verify_enabled: bool = False
    payment_auto_verify_shadow_mode: bool = True
    gmail_oauth_redirect_uri: str = ""
    gmail_verification_account_email: str = ""
    gmail_owner_email: str = ""  # legacy name retained for existing deployments
    gmail_hdfc_search_query: str = ""
    gmail_poll_interval_seconds: int = 60
    hdfc_credit_email_from: str = ""
    hdfc_forwarder_email: str = ""
    hdfc_expected_account_last4: str = ""
    gmail_paytm_search_query: str = ""
    paytm_merchant_email_from: str = ""
    paytm_forwarder_email: str = ""
    paytm_expected_merchant_name: str = ""
    tesseract_cmd: str = ""
    tesseract_language: str = "eng"
    payment_ocr_enabled: bool = True

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

    @property
    def google_oauth_configured(self) -> bool:
        return bool(
            self.google_oauth_client_id
            and self.google_oauth_client_secret
            and self.google_oauth_redirect_uri
            and self.google_token_encryption_key
        )

    @property
    def gmail_verification_configured(self) -> bool:
        return bool(
            self.google_oauth_client_id
            and self.google_oauth_client_secret
            and self.gmail_oauth_redirect_uri
            and self.google_token_encryption_key
            and (self.hdfc_gmail_source_configured or self.paytm_merchant_source_configured)
        )

    @property
    def hdfc_gmail_source_configured(self) -> bool:
        return bool(
            self.gmail_hdfc_search_query
            and self.hdfc_credit_email_from
            and len(self.hdfc_expected_account_last4) == 4
        )

    @property
    def paytm_merchant_source_configured(self) -> bool:
        return bool(
            self.gmail_paytm_search_query
            and self.paytm_merchant_email_from
            and self.paytm_expected_merchant_name
        )

    @property
    def payment_ocr_configured(self) -> bool:
        return self.payment_ocr_enabled and bool(self.tesseract_language)


@lru_cache
def get_settings() -> Settings:
    return Settings()

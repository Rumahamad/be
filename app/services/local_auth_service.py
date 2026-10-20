"""Local identities, expiring sessions, rotating refresh tokens and one-use recovery."""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import urlencode
from uuid import UUID, uuid4

import bcrypt
import httpx
import jwt
from sqlalchemy import select, update

from app.config.settings import get_settings
from app.db.session import SessionLocal
from app.models.enums import UserStatus
from app.models.identity import User
from app.models.local_auth import LocalIdentity, LocalSession, LocalToken
from app.services.auth_service import AuthProviderError, AuthSession
from app.services.email_service import EmailDeliveryError, OutgoingEmail, configured_email_provider


def now():
    return datetime.now(UTC)


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    if not 8 <= len(password) <= 255:
        raise AuthProviderError("Password must contain between 8 and 255 characters")
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1,
                           maxmem=256 * 1024 * 1024)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(value).decode()


def check_password(password: str, encoded: str | None) -> bool:
    try:
        if not encoded:
            # Comparable work for unknown/passwordless identities.
            hashlib.scrypt(password.encode(), salt=b"bnc-login-padding", n=2**17, r=8, p=1,
                           maxmem=256 * 1024 * 1024)
            return False
        if encoded.startswith(("$2a$", "$2b$", "$2y$")):
            # Supabase legacy hashes use bcrypt's 72-byte password limit.
            return bcrypt.checkpw(password.encode()[:72], encoded.encode())
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        value = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                               n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024)
        return hmac.compare_digest(value, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


class LocalAuthService:
    def __init__(self, settings=None, session_factory=None):
        self.settings = settings or get_settings()
        self.session_factory = session_factory or SessionLocal

    def _key(self):
        if len(self.settings.local_auth_secret) < 32:
            raise AuthProviderError("LOCAL_AUTH_SECRET must contain at least 32 random characters")
        return self.settings.local_auth_secret

    @staticmethod
    def _approved(db, identity_id):
        member = db.scalar(select(User).where(User.auth_user_id == identity_id))
        if not member or member.status != UserStatus.ACTIVE:
            raise AuthProviderError("Invalid login credentials")
        return member

    def _new_session(self, db, identity_id):
        session = LocalSession(id=uuid4(), identity_id=identity_id,
            expires_at=now() + timedelta(seconds=self.settings.auth_refresh_cookie_max_age))
        db.add(session)
        db.flush()
        return self._issue(db, session)

    def _issue(self, db, session):
        refresh = secrets.token_urlsafe(48)
        db.add(LocalToken(digest=token_digest(refresh), purpose="refresh",
            identity_id=session.identity_id, session_id=session.id, expires_at=session.expires_at))
        issued = now()
        access = jwt.encode({"sub": str(session.identity_id), "sid": str(session.id),
            "iss": self.settings.local_auth_issuer, "aud": "bnc", "iat": issued,
            "exp": issued + timedelta(seconds=self.settings.local_auth_access_seconds)},
            self._key(), algorithm="HS256")
        return AuthSession(access, refresh, self.settings.local_auth_access_seconds)

    def login(self, identifier, password):
        invalid = False
        with self.session_factory() as db, db.begin():
            identity = db.scalar(select(LocalIdentity).where(
                LocalIdentity.email == identifier.strip().lower()).with_for_update())
            if identity and identity.locked_until and identity.locked_until > now():
                raise AuthProviderError("Invalid login credentials")
            if not check_password(password, identity.password_hash if identity else None):
                if identity:
                    identity.failed_attempts += 1
                    if identity.failed_attempts >= 10:
                        identity.locked_until = now() + timedelta(minutes=15)
                invalid = True
            else:
                self._approved(db, identity.id)
                identity.failed_attempts = 0
                identity.locked_until = None
                if identity.password_hash.startswith("$2") and len(password.encode()) <= 72:
                    identity.password_hash = hash_password(password)
                result = self._new_session(db, identity.id)
        if invalid:
            raise AuthProviderError("Invalid login credentials")
        return result

    def refresh(self, refresh_token):
        rejected = False
        with self.session_factory() as db, db.begin():
            # Lock the session before its tokens; password reset uses the same ordering.
            candidate = db.get(LocalToken, token_digest(refresh_token))
            if not candidate or candidate.purpose != "refresh":
                raise AuthProviderError("Invalid or expired session")
            session = db.scalar(select(LocalSession).where(
                LocalSession.id == candidate.session_id).with_for_update())
            token = db.scalar(select(LocalToken).where(LocalToken.digest == candidate.digest)
                              .with_for_update().execution_options(populate_existing=True))
            if not session or session.revoked_at or session.expires_at <= now():
                raise AuthProviderError("Invalid or expired session")
            if token.consumed_at or token.expires_at <= now():
                session.revoked_at = now()
                rejected = True
            else:
                self._approved(db, session.identity_id)
                token.consumed_at = now()
                result = self._issue(db, session)
        if rejected:
            raise AuthProviderError("Invalid or expired session")
        return result

    def decode(self, token):
        try:
            return jwt.decode(token, self._key(), algorithms=["HS256"], audience="bnc",
                issuer=self.settings.local_auth_issuer,
                options={"require": ["exp", "iat", "sub", "sid"]})
        except jwt.PyJWTError as exc:
            raise AuthProviderError("Invalid or expired access token") from exc

    def validate(self, token):
        claims = self.decode(token)
        try:
            identity_id, session_id = UUID(claims["sub"]), UUID(claims["sid"])
        except (ValueError, TypeError) as exc:
            raise AuthProviderError("Invalid access token") from exc
        with self.session_factory() as db:
            session = db.get(LocalSession, session_id)
            if (not session or session.identity_id != identity_id or session.revoked_at
                    or session.expires_at <= now()):
                raise AuthProviderError("Invalid or expired session")
        return claims

    def logout(self, access_token):
        try:
            claims = self.decode(access_token)
        except AuthProviderError:
            return
        with self.session_factory() as db, db.begin():
            db.execute(update(LocalSession).where(LocalSession.id == UUID(claims["sid"]))
                       .values(revoked_at=now()))

    def verify_password(self, email, password):
        # Login enforces the same failure counters; immediately revoke its temporary session.
        session = self.login(email, password)
        self.logout(session.access_token)

    def update_password(self, access_token, password):
        claims = self.validate(access_token)
        encoded = hash_password(password)
        with self.session_factory() as db, db.begin():
            identity = db.scalar(select(LocalIdentity).where(
                LocalIdentity.id == UUID(claims["sub"])).with_for_update())
            self._approved(db, identity.id)
            identity.password_hash = encoded
            identity.failed_attempts = 0
            identity.locked_until = None
            db.execute(update(LocalSession).where(LocalSession.identity_id == identity.id,
                LocalSession.id != UUID(claims["sid"])).values(revoked_at=now()))
            db.execute(update(LocalToken).where(LocalToken.identity_id == identity.id,
                LocalToken.purpose == "recovery", LocalToken.consumed_at.is_(None))
                .values(consumed_at=now()))

    def request_password_reset(self, email, redirect_to):
        with self.session_factory() as db:
            identity = db.scalar(select(LocalIdentity).where(LocalIdentity.email == email.lower()))
            if not identity:
                return
            member = db.scalar(select(User).where(User.auth_user_id == identity.id))
            if not member or member.status != UserStatus.ACTIVE:
                return
            identity_id = identity.id
        self.send_link(identity_id, email, redirect_to)

    def send_link(self, identity_id, email, redirect_to):
        provider = configured_email_provider(self.settings)
        if provider is None:
            raise AuthProviderError("SMTP email delivery must be configured for password links")
        raw = secrets.token_urlsafe(48)
        # Use a single recovery flow for invitations too; GET never consumes the link.
        link = self.settings.frontend_url.rstrip("/") + "/auth/reset-password?" + urlencode({
            "token_hash": raw, "type": "recovery"})
        with self.session_factory() as db, db.begin():
            db.add(LocalToken(digest=token_digest(raw), purpose="recovery", identity_id=identity_id,
                expires_at=now() + timedelta(seconds=self.settings.local_auth_link_seconds)))
        try:
            provider.send(OutgoingEmail(recipient=email, subject="Set your BNC password",
                text=f"Set your BNC password using this one-use link:\n\n{link}\n\n"
                     "If you did not request this, ignore this email."))
        except EmailDeliveryError as exc:
            with self.session_factory() as db, db.begin():
                db.execute(update(LocalToken).where(LocalToken.digest == token_digest(raw))
                           .values(consumed_at=now()))
            raise AuthProviderError("Password email could not be delivered") from exc

    def recover_password(self, raw, password):
        encoded = hash_password(password)
        with self.session_factory() as db, db.begin():
            candidate = db.get(LocalToken, token_digest(raw))
            if not candidate or candidate.purpose != "recovery":
                raise AuthProviderError("Password link is invalid or expired")
            identity = db.scalar(select(LocalIdentity).where(
                LocalIdentity.id == candidate.identity_id).with_for_update())
            token = db.scalar(select(LocalToken).where(LocalToken.digest == candidate.digest)
                              .with_for_update().execution_options(populate_existing=True))
            if token.consumed_at or token.expires_at <= now():
                raise AuthProviderError("Password link is invalid or expired")
            member = self._approved(db, identity.id)
            identity.password_hash = encoded
            identity.failed_attempts = 0
            identity.locked_until = None
            member.password_setup_required = False
            db.execute(update(LocalSession).where(LocalSession.identity_id == identity.id)
                       .values(revoked_at=now()))
            db.execute(update(LocalToken).where(LocalToken.identity_id == identity.id,
                LocalToken.purpose == "recovery").values(consumed_at=now()))

    def begin_google(self, return_to):
        if not self.settings.google_oauth_client_id or not self.settings.google_oauth_client_secret:
            raise AuthProviderError("Google sign-in is not configured")
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        with self.session_factory() as db, db.begin():
            db.add(LocalToken(digest=token_digest(state), purpose="google", expires_at=now()
                + timedelta(minutes=10), context={"return_to": return_to, "nonce": nonce,
                                                "verifier": verifier}))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": self.settings.google_oauth_client_id,
            "redirect_uri": self.settings.google_login_redirect_uri, "response_type": "code",
            "scope": "openid email profile", "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        return url, state

    def finish_google(self, code, state):
        with self.session_factory() as db, db.begin():
            token = db.scalar(select(LocalToken).where(LocalToken.digest == token_digest(state))
                              .with_for_update())
            if not token or token.purpose != "google" or token.consumed_at or token.expires_at <= now():
                raise AuthProviderError("Google sign-in expired; try again")
            token.consumed_at = now()
            context = token.context
        try:
            response = httpx.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.settings.google_oauth_client_id,
                "client_secret": self.settings.google_oauth_client_secret, "code": code,
                "redirect_uri": self.settings.google_login_redirect_uri,
                "grant_type": "authorization_code", "code_verifier": context["verifier"]}, timeout=15)
            response.raise_for_status()
            encoded = response.json()["id_token"]
            key = google_jwks().get_signing_key_from_jwt(encoded)
            claims = jwt.decode(encoded, key.key, algorithms=["RS256"],
                audience=self.settings.google_oauth_client_id, issuer="https://accounts.google.com",
                options={"require": ["exp", "iat", "sub", "nonce", "email"]})
            if claims["nonce"] != context["nonce"] or claims.get("email_verified") is not True:
                raise ValueError("Unverified identity")
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError) as exc:
            raise AuthProviderError("Google sign-in could not be verified") from exc
        with self.session_factory() as db, db.begin():
            identity = db.scalar(select(LocalIdentity).where(
                LocalIdentity.email == claims["email"].lower()).with_for_update())
            if not identity:
                raise AuthProviderError("User is not approved for BNC")
            self._approved(db, identity.id)
            if identity.google_subject and identity.google_subject != claims["sub"]:
                raise AuthProviderError("Google account does not match this member")
            # Google is authoritative for Gmail and managed Workspace accounts.
            if not identity.google_subject and not (claims["email"].lower().endswith("@gmail.com")
                                                   or claims.get("hd")):
                raise AuthProviderError("Use your BNC password for this email address")
            identity.google_subject = claims["sub"]
            result = self._new_session(db, identity.id)
        return result, context["return_to"]


@lru_cache
def google_jwks():
    return jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", lifespan=3600)

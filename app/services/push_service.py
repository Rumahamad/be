"""Web Push notification delivery service (RFC 8030 / VAPID)."""
from __future__ import annotations

import json
import logging
import struct
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.hmac import HMAC

logger = logging.getLogger(__name__)


def _b64_pad(s: str) -> str:
    """Re-pad a urlsafe base64 string for decoding."""
    return s + "=" * (-len(s) % 4)


def _load_private_key(pem: str) -> ec.EllipticCurvePrivateKey:
    pem_bytes = pem.replace("\\n", "\n").encode()
    return serialization.load_pem_private_key(pem_bytes, password=None, backend=default_backend())


def _sign_jwt(claims: dict, private_key: ec.EllipticCurvePrivateKey) -> str:
    """Build and sign a VAPID JWT (ES256) without external jwt lib dependency."""
    header = {"typ": "JWT", "alg": "ES256"}
    def _b64(d: dict | Any) -> str:
        return urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).decode().rstrip("=")

    signing_input = f"{_b64(header)}.{_b64(claims)}".encode()
    sig = private_key.sign(signing_input, ec.ECDSA(SHA256()))
    r, s = decode_dss_signature(sig)
    # Convert r,s to 64-byte raw form
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input.decode()}.{urlsafe_b64encode(raw_sig).decode().rstrip('=')}"


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF with SHA-256."""
    backend = default_backend()
    # extract
    h = HMAC(salt, SHA256(), backend=backend)
    h.update(ikm)
    prk = h.finalize()
    # expand
    h = HMAC(prk, SHA256(), backend=backend)
    h.update(info + b"\x01")
    return h.finalize()[:length]


def encrypt_payload(
    payload: bytes,
    endpoint: str,
    p256dh: str,
    auth_secret: str,
) -> tuple[bytes, bytes, bytes]:
    """
    Encrypt a push payload using RFC 8291 (aes128gcm content encoding).
    Returns (ciphertext_with_header, salt, server_public_key_bytes).
    """
    # Decode recipient keys
    receiver_pub_bytes = urlsafe_b64decode(_b64_pad(p256dh))
    auth_bytes = urlsafe_b64decode(_b64_pad(auth_secret))

    # Generate an ephemeral server key pair
    server_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    server_pub = server_key.public_key()
    server_pub_bytes = server_pub.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    # Load recipient public key
    receiver_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver_pub_bytes)

    # ECDH shared secret
    shared_secret = server_key.exchange(ec.ECDH(), receiver_pub)

    # RFC 8291 key derivation
    salt = __import__("os").urandom(16)

    # PRK = HKDF-Extract(auth_secret, shared_secret)
    prk_key = _hkdf(auth_bytes, shared_secret, b"WebPush: info\x00" + receiver_pub_bytes + server_pub_bytes, 32)

    # CEK and nonce
    cek = _hkdf(salt, prk_key, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, prk_key, b"Content-Encoding: nonce\x00", 12)

    # Pad and encrypt: add record delimiter \x02
    padded = payload + b"\x02"
    aesgcm = AESGCM(cek)
    ciphertext = aesgcm.encrypt(nonce, padded, None)

    # Build RFC 8291 content header: salt(16) + rs(4, big-endian=4096) + idlen(1) + server_public_key(65)
    rs = 4096
    content_header = salt + struct.pack(">I", rs) + bytes([len(server_pub_bytes)]) + server_pub_bytes
    return content_header + ciphertext, salt, server_pub_bytes


class PushDeliveryError(Exception):
    pass


def send_push(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    icon: str = "/icons/bnc-192.png",
    tag: str = "",
    url: str = "/",
    actions: list[dict[str, str]] | None = None,
    action_urls: dict[str, str] | None = None,
    vapid_public_key: str,
    vapid_private_key_pem: str,
    vapid_subject: str,
    ttl: int = 86400,
) -> None:
    """
    Send a single Web Push notification to one subscription.
    Raises PushDeliveryError on 4xx/5xx responses.
    """
    private_key = _load_private_key(vapid_private_key_pem)

    payload_data = {
        "title": title,
        "body": body,
        "icon": icon,
        "tag": tag or title[:40],
        "data": {"url": url, "action_urls": action_urls or {}},
    }
    if actions:
        payload_data["actions"] = actions[:2]
    payload_bytes = json.dumps(payload_data).encode()

    encrypted, _salt, _spub = encrypt_payload(payload_bytes, endpoint, p256dh, auth)

    # Build VAPID JWT
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    now = int(time.time())
    claims = {
        "aud": audience,
        "exp": now + 43200,  # 12 hours
        "sub": vapid_subject,
    }
    jwt_token = _sign_jwt(claims, private_key)

    pub_key_b64 = vapid_public_key.rstrip("=")

    headers = {
        "Authorization": f"vapid t={jwt_token},k={pub_key_b64}",
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
    }

    with httpx.Client(timeout=15) as client:
        resp = client.post(endpoint, content=encrypted, headers=headers)

    if resp.status_code == 410:
        raise PushDeliveryError("GONE:410")
    if resp.status_code == 404:
        raise PushDeliveryError("GONE:404")
    if resp.status_code >= 400:
        raise PushDeliveryError(
            f"Push failed {resp.status_code}: {resp.text[:200]}"
        )

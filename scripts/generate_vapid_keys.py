from base64 import urlsafe_b64encode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def without_padding(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("ascii").rstrip("=")


if __name__ == "__main__":
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii").strip()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    private_env = private_pem.replace("\n", "\\n")
    print(f"VAPID_PUBLIC_KEY={without_padding(public_key)}")
    print(f"VAPID_PRIVATE_KEY_PEM={private_env}")

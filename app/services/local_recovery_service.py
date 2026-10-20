"""Encrypted disaster recovery; no credentials or password hashes in Sheets."""
import json
from pathlib import Path

from cryptography.fernet import Fernet

from app.engines.backup.archive import verify_archive, write_artifact
from app.engines.backup.postgres import dump_database


def recovery_cipher(settings):
    if not settings.backup_encryption_key:
        raise ValueError("BACKUP_ENCRYPTION_KEY is required for a complete local backup")
    return Fernet(settings.backup_encryption_key.encode("ascii"))


def write_local_recovery(root, settings, snapshot):
    cipher = recovery_cipher(settings)
    # The encryption key must be retained separately from this archive.
    configuration = {key: value for key, value in settings.model_dump().items()
                     if key != "backup_encryption_key" and not key.startswith("supabase_")}
    return [
        write_artifact(root, "recovery/database.dump.fernet",
                       cipher.encrypt(dump_database(settings, snapshot))),
        write_artifact(root, "recovery/configuration.json.fernet",
                       cipher.encrypt(json.dumps(configuration).encode())),
    ]


def seal_local_manifest(root: Path, settings):
    write_artifact(root, "recovery/manifest.fernet",
                   recovery_cipher(settings).encrypt((root / "manifest.json").read_bytes()))


def verify_local_recovery(root: Path, settings):
    cipher = recovery_cipher(settings)
    authenticated = cipher.decrypt((root / "recovery/manifest.fernet").read_bytes())
    if authenticated != (root / "manifest.json").read_bytes():
        raise ValueError("Authenticated backup manifest does not match")
    result = verify_archive(root)
    if not json.loads(authenticated).get("local_recovery_included"):
        raise ValueError("This backup does not contain local disaster recovery data")
    return result

"""Restore a verified encrypted backup into an EMPTY local database and storage root."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from dotenv import set_key
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config.settings import Settings
from app.engines.backup.postgres import restore_database
from app.services.local_recovery_service import recovery_cipher, verify_local_recovery
from app.services.storage_service import LocalStorageService


def restore(archive: Path, settings: Settings, output_env: Path):
    parsed = make_url(settings.database_url)
    if parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Restore target must be a local PostgreSQL database")
    if output_env.exists() or output_env.name == ".env":
        raise ValueError("Choose a new staging configuration, never the active .env")
    storage = LocalStorageService(settings)
    if storage.root.exists() and any(storage.root.iterdir()):
        raise ValueError("Restore target storage must be empty")
    engine = create_engine(settings.database_url)
    if inspect(engine).get_table_names(schema="public"):
        raise ValueError("Restore target database must be empty")
    verify_local_recovery(archive, settings)
    cipher = recovery_cipher(settings)
    configuration = json.loads(cipher.decrypt((archive / "recovery/configuration.json.fernet").read_bytes()))
    plaintext = cipher.decrypt((archive / "recovery/database.dump.fernet").read_bytes())
    with tempfile.TemporaryDirectory(prefix="bnc-restore-") as directory:
        dump = Path(directory) / "database.dump"
        dump.write_bytes(plaintext)
        restore_database(settings.postgres_bin, dump, settings.database_url)
    manifest = json.loads((archive / "manifest.json").read_bytes())
    evidence = {item["file_id"]: item for item in manifest["artifacts"] if "file_id" in item}
    with engine.connect() as connection:
        files = list(connection.execute(text("SELECT * FROM files WHERE status='ACTIVE'")).mappings())
    if set(evidence) != {str(row["id"]) for row in files}:
        raise ValueError("Restored database and backup evidence inventories differ")
    for row in files:
        item = evidence[str(row["id"])]
        content = (archive / item["path"]).read_bytes()
        if len(content) != row["size_bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise ValueError("Restored attachment failed verification")
        storage.upload(row["bucket_name"], row["object_key"], content, row["mime_type"])
    with engine.begin() as connection:
        connection.execute(text("UPDATE files SET storage_provider='LOCAL'"))
        connection.execute(text("UPDATE local_auth_sessions SET revoked_at=now()"))
        connection.execute(text("UPDATE local_auth_tokens SET consumed_at=now()"))
        connection.execute(text("UPDATE backup_runs SET status='FAILED',error_code='RESTORED_BACKUP' "
                                "WHERE status IN ('PENDING','RUNNING')"))
        connection.execute(text("UPDATE notification_outbox SET status='CANCELLED' "
                                "WHERE status IN ('PENDING','FAILED')"))
    configuration.update(database_url=settings.database_url, local_storage_root=str(storage.root),
        postgres_bin=settings.postgres_bin, auth_provider="local", storage_provider="LOCAL",
        backup_encryption_key=settings.backup_encryption_key, payment_auto_verify_enabled=False,
        payment_auto_verify_shadow_mode=True)
    output_env.touch(exist_ok=False)
    for key, value in configuration.items():
        serialized = json.dumps(value) if isinstance(value, (list, bool, dict)) else str(value)
        set_key(str(output_env), key.upper(), serialized)
    engine.dispose()
    return {"files": len(files), "sessions_revoked": True, "active_configuration_changed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target-env", type=Path, required=True,
                        help="Local target URL, empty storage root, and backup decryption key")
    parser.add_argument("--output-env", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.archive, Settings(_env_file=args.target_env), args.output_env)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- CLI boundary must never print credentials.
        print(f"Restore stopped ({type(exc).__name__}); active configuration unchanged.")
        raise SystemExit(1)

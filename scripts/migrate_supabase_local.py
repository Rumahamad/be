"""Read-only Supabase export into an EMPTY local database; never changes active .env."""
import argparse
import hashlib
import json
import secrets
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.engines.backup.postgres import dump_database, restore_database
from app.models.local_auth import LocalIdentity, LocalSession, LocalToken
from app.services.storage_service import LocalStorageService, StorageError, SupabaseStorageService
from scripts.local_postgres import BIN, CREDENTIALS, ROOT, local_url


def row_digest(rows):
    def encode(value):
        if isinstance(value, datetime) and value.tzinfo:
            return value.astimezone(UTC).isoformat()
        if isinstance(value, (UUID, Decimal, datetime, date)):
            return str(value)
        if isinstance(value, bytes):
            return value.hex()
        raise TypeError(type(value).__name__)
    encoded = sorted(json.dumps(dict(row), default=encode, sort_keys=True) for row in rows)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="Verify and finish a staged import")
    args = parser.parse_args()
    source_settings = Settings(_env_file=ROOT / ".env")
    if "supabase" not in source_settings.database_url:
        raise RuntimeError("Active configuration is not a Supabase source")
    credentials = json.loads(CREDENTIALS.read_text())
    target_url = local_url(credentials)
    target_engine = create_engine(target_url)
    if inspect(target_engine).get_table_names(schema="public") and not args.resume:
        raise RuntimeError("Target database must be empty; existing data will never be overwritten")
    staging = ROOT / ".local" / "migration"
    staging.mkdir(parents=True, exist_ok=True)
    env_path = ROOT / ".env.local"
    existing = dotenv_values(env_path) if env_path.exists() else {}
    if not env_path.exists():
        shutil.copy2(ROOT / ".env", env_path)
    overrides = {
        "DATABASE_URL": target_url, "AUTH_PROVIDER": "local", "STORAGE_PROVIDER": "LOCAL",
        "LOCAL_STORAGE_ROOT": str(ROOT / ".local" / "storage"),
        "STORAGE_BUCKET": source_settings.supabase_storage_bucket,
        "LOCAL_AUTH_SECRET": existing.get("LOCAL_AUTH_SECRET") or secrets.token_urlsafe(48),
        "BACKUP_ENCRYPTION_KEY": existing.get("BACKUP_ENCRYPTION_KEY") or Fernet.generate_key().decode(), "POSTGRES_BIN": str(BIN),
    }
    for key, value in overrides.items():
        set_key(str(env_path), key, value)
    settings = Settings(_env_file=env_path)
    cipher = Fernet(settings.backup_encryption_key.encode())
    source = create_engine(source_settings.database_url, connect_args={"connect_timeout": 10})
    inventory = {}
    with source.connect().execution_options(isolation_level="REPEATABLE READ") as connection:  # noqa: SIM117
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            snapshot = connection.scalar(text("SELECT pg_export_snapshot()"))
            dump = dump_database(source_settings, snapshot)
            (staging / "source.dump.fernet").write_bytes(cipher.encrypt(dump))
            tables = inspect(connection).get_table_names(schema="public")
            for name in tables:
                quoted = connection.dialect.identifier_preparer.quote(name)
                rows = list(connection.execute(text(f'SELECT * FROM public.{quoted}')).mappings())
                inventory[name] = {"count": len(rows), "sha256": row_digest(rows)}
            identities = list(connection.execute(text(
                "SELECT a.id, lower(a.email) AS email, a.encrypted_password AS password_hash "
                "FROM auth.users a JOIN public.users u ON u.auth_user_id=a.id")).mappings())
            google = dict(connection.execute(text("SELECT i.user_id, i.identity_data->>'sub' "
                "FROM auth.identities i JOIN public.users u ON u.auth_user_id=i.user_id "
                "WHERE i.provider='google'")).all())
            files = list(connection.execute(text("SELECT * FROM public.files")).mappings())
    if not args.resume:
        raw_dump = staging / "restore.tmp"
        raw_dump.write_bytes(dump)
        try:
            restore_database(BIN, raw_dump, target_url)
        finally:
            raw_dump.unlink(missing_ok=True)
    with target_engine.connect() as connection:
        for name, expected in inventory.items():
            quoted = connection.dialect.identifier_preparer.quote(name)
            rows = list(connection.execute(text(f'SELECT * FROM public.{quoted}')).mappings())
            if len(rows) != expected["count"] or row_digest(rows) != expected["sha256"]:
                raise RuntimeError(f"Restored table failed verification: {name}")
    for model in (LocalIdentity, LocalSession, LocalToken):
        model.__table__.create(target_engine, checkfirst=True)
    with Session(target_engine) as db, db.begin():
        for row in identities:
            if not db.get(LocalIdentity, row["id"]):
                db.add(LocalIdentity(id=row["id"], email=row["email"],
                    password_hash=row["password_hash"] or None, google_subject=google.get(row["id"])))
    remote_storage = SupabaseStorageService(source_settings)
    local_storage = LocalStorageService(settings)
    file_manifest, missing_files = [], []
    for number, row in enumerate(files, 1):
        if row["status"] != "ACTIVE":
            continue
        try:
            content, mime = remote_storage.download(row["bucket_name"], row["object_key"])
        except StorageError:
            missing_files.append(str(row["id"]))
            continue
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != row["size_bytes"] or row["checksum"] and row["checksum"] != digest:
            raise RuntimeError("Source attachment failed integrity check")
        if not local_storage._path(row["bucket_name"], row["object_key"]).exists():
            local_storage.upload(row["bucket_name"], row["object_key"], content, mime)
        stored, _ = local_storage.download(row["bucket_name"], row["object_key"])
        if hashlib.sha256(stored).hexdigest() != digest:
            raise RuntimeError("Local attachment failed integrity check")
        file_manifest.append({"id": str(row["id"]), "sha256": digest})
        if number % 25 == 0:
            print(f"Copied and verified {number}/{len(files)} private files", flush=True)
    with target_engine.begin() as connection:
        for copied in file_manifest:
            connection.execute(text("UPDATE files SET storage_provider='LOCAL' WHERE id=:id"),
                               {"id": UUID(copied["id"])})
        # Preserve all other source rows exactly. Only the local schema is advanced.
        connection.execute(text("UPDATE alembic_version SET version_num='0022_local_auth'"))
    (staging / "verification.json").write_text(json.dumps({"tables": inventory,
        "files": file_manifest, "identities": len(identities), "google_identities": len(google),
        "missing_files": missing_files, "status": "BLOCKED_MISSING_FILES" if missing_files else "STAGED",
        "source_changed_after_export": "NOT_CHECKED"}, indent=2))
    print(f"Staged {len(tables)} tables, {len(identities)} identities, {len(file_manifest)} files")
    print("Active .env was not changed. Verify, check source drift, then cut over.")
    if missing_files:
        print(f"Cutover blocked: {len(missing_files)} source files unavailable; see verification.json")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- CLI must not expose credentials or member data.
        print(f"Migration stopped ({type(exc).__name__}). Active configuration unchanged.")
        if isinstance(exc, RuntimeError):
            print(str(exc))
        raise SystemExit(1)

"""Explicit local recovery export; never runs on the payment request path."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.db.session import Base, engine
from app.engines.backup.archive import finish_manifest, write_artifact, write_dataset
from app.engines.backup.layout import weekly_folder
from app.models import (  # noqa: F401
    announcements, audit, communications, expense_reversals, expenses,
    files, fund, identity, payments, reversals, settings,
)
from app.services.storage_service import StorageError, SupabaseStorageService

# Explicit inventory: new tables require a backup policy review. Auth, live delivery
# queues and push credentials intentionally do not belong in recovery artifacts.
DATASETS = (
    "roles", "permissions", "role_permissions", "users", "deleted_users", "groups",
    "user_groups", "user_preferences", "payments", "payment_allocations",
    "member_month_contributions", "payment_revisions", "payment_allocation_revisions",
    "payment_reviews", "payment_files", "files", "receipts", "payment_reversals",
    "expense_categories", "expenses", "expense_attachments", "expense_reversals",
    "fund_accounts", "fund_entries", "announcements", "announcement_targets",
    "announcement_reads", "notifications", "organization_settings", "audit_logs",
    "incoming_upi_credits", "payment_proof_extractions", "payment_verification_events",
)
FORBIDDEN_KEYS = {
    "access_token", "refresh_token", "encrypted_refresh_token", "password",
    "password_hash", "client_secret", "database_url", "smtp_password", "jwt_secret",
    "vapid_private_key", "otp", "reset_token", "api_key", "service_role_key",
}


def reject_secret_fields(value) -> None:
    """Fail closed instead of silently exporting or redacting new credential fields."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError("Credential field detected; review backup policy")
            reject_secret_fields(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_secret_fields(item)


def create_local_snapshot(destination: Path, run_id=None, *, include_evidence: bool = True) -> Path:
    started = datetime.now(UTC)
    run_id = str(run_id or uuid4())
    root = destination.resolve() / Path(str(weekly_folder(
        started.astimezone(ZoneInfo("Asia/Kolkata")), run_id,
    )))
    root.mkdir(parents=True, exist_ok=False)
    artifacts, errors, file_rows, table_schemas = [], [], [], {}
    # One consistent PostgreSQL snapshot for every relation; no writes or locks
    # on application rows. Download immutable object versions after releasing it.
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            source_cutoff = connection.scalar(text("SELECT transaction_timestamp()"))
            migration = connection.execute(text("SELECT version_num FROM alembic_version"))
            versions = sorted(migration.scalars().all())
            for name in DATASETS:
                table = Base.metadata.tables[name]
                statement = select(table).order_by(*table.primary_key.columns)
                rows = [dict(row) for row in connection.execute(statement).mappings()]
                # PostgreSQL timestamp-without-time-zone is a wall-clock value,
                # not UTC. Preserve it exactly; never invent a timezone.
                for row in rows:
                    for key, value in row.items():
                        if isinstance(value, datetime) and value.tzinfo is None:
                            row[key] = value.isoformat()
                table_schemas[name] = {
                    "primary_key": [column.name for column in table.primary_key],
                    "foreign_keys": [
                        {"columns": [element.parent.name for element in constraint.elements],
                         "target_table": constraint.referred_table.name,
                         "target_columns": [element.column.name for element in constraint.elements]}
                        for constraint in table.foreign_key_constraints
                        if constraint.referred_table.name in DATASETS
                    ],
                }
                reject_secret_fields(rows)
                artifacts.append(write_dataset(root, name, rows))
                if name == "files":
                    file_rows = rows
    storage = SupabaseStorageService()
    for row in file_rows if include_evidence else ():
        try:
            if row["storage_provider"] != "SUPABASE":
                raise ValueError("Unsupported evidence provider")
            content, _ = storage.download(row["bucket_name"], row["object_key"])
            if len(content) != row["size_bytes"]:
                raise ValueError("Evidence size mismatch")
            artifact = write_artifact(root, f"evidence/{row['id']}.bin", content)
            # Existing checksums may be absent; this run always computes SHA-256.
            if row["checksum"] and row["checksum"] != artifact["sha256"]:
                raise ValueError("Evidence checksum mismatch")
            artifacts.append({**artifact, "file_id": str(row["id"])})
        except (StorageError, ValueError) as exc:
            # Provider messages can contain private paths. Keep diagnostics bounded.
            errors.append({"file_id": str(row["id"]), "error_type": type(exc).__name__})
    finish_manifest(root, {
        "run_id": run_id, "started_at": started, "source_cutoff": source_cutoff,
        "completed_at": datetime.now(UTC), "alembic_versions": versions,
        "status": "PARTIAL" if errors else "EXPORTED", "errors": errors,
        "table_schemas": table_schemas,
        "scope": "BNC business tables and registered evidence",
        "exclusions": ["Supabase Auth credentials/sessions", "push subscriptions",
                       "notification delivery queues", "deployment secrets",
                       "unregistered storage objects", "source code",
                       *([] if include_evidence else ["binary evidence (Sheets mirror only)"])],
        "auth_recovery": "Reprovision/relink identities for a new Supabase project",
    }, artifacts)
    return root

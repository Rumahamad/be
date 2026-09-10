from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.backup import BackupRun, GoogleConnection


def queue_monthly_backup_if_due(now: datetime | None = None) -> bool:
    """Queue one automatic recovery point per Kolkata calendar month."""
    local_now = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Kolkata"))
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    with SessionLocal() as db:
        connected = db.scalar(select(GoogleConnection.id).where(
            GoogleConnection.purpose == "DRIVE_BACKUP",
            GoogleConnection.status == "ACTIVE",
        ))
        if not connected:
            return False
        existing = db.scalar(select(BackupRun.id).where(
            BackupRun.run_type == "MONTHLY",
            BackupRun.created_at >= month_start,
        ).limit(1))
        active = db.scalar(select(BackupRun.id).where(
            BackupRun.status.in_(("PENDING", "RUNNING")),
        ).limit(1))
        if existing or active:
            return False
        db.add(BackupRun(run_type="MONTHLY", trigger_type="SCHEDULED"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False
        return True

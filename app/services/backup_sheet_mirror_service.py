"""Coalesced near-real-time Google Sheets mirror from durable DB events."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from app.db.session import SessionLocal
from app.engines.backup.google_drive import GoogleDriveClient
from app.engines.backup.google_sheets import GoogleSheetsClient
from app.engines.backup.sheets_projection import available_months, build_current_users, build_yearly_master
from app.models.backup import BackupOutbox, GoogleConnection
from app.services.backup_snapshot_service import create_local_snapshot
from app.services.google_backup_oauth_service import GoogleBackupOAuthError, GoogleBackupOAuthService


class BackupSheetMirrorService:
    oauth = GoogleBackupOAuthService()
    max_attempts = 5

    def process_due(self, limit: int = 200) -> int:
        event_ids = self._claim(limit)
        if not event_ids:
            return 0
        try:
            self._refresh()
            self._complete(event_ids)
        except Exception:
            self._retry(event_ids)
            return 0
        return len(event_ids)

    def _claim(self, limit: int) -> list:
        now = datetime.now(UTC)
        with SessionLocal() as db, db.begin():
            events = db.scalars(
                select(BackupOutbox).where(
                    BackupOutbox.attempt_count < self.max_attempts,
                    BackupOutbox.next_retry_at <= now,
                    or_(
                        BackupOutbox.status.in_(("PENDING", "FAILED")),
                        and_(BackupOutbox.status == "PROCESSING", BackupOutbox.lease_until < now),
                    ),
                ).order_by(BackupOutbox.created_at).with_for_update(skip_locked=True).limit(limit)
            ).all()
            for event in events:
                event.status = "PROCESSING"
                event.attempt_count += 1
                event.lease_until = now + timedelta(minutes=5)
            return [event.id for event in events]

    def _refresh(self) -> None:
        with SessionLocal() as db:
            connection = db.scalar(select(GoogleConnection).where(
                GoogleConnection.purpose == "DRIVE_BACKUP",
                GoogleConnection.status == "ACTIVE",
            ))
            if not connection:
                raise GoogleBackupOAuthError("Google Drive is not connected")
            access_token = self.oauth.access_token(connection)
            connection_id = connection.id
        with TemporaryDirectory(prefix="bnc-sheets-") as temp_dir:
            snapshot = create_local_snapshot(
                Path(temp_dir), run_id=f"sheets-{uuid4()}", include_evidence=False,
            )
            drive = GoogleDriveClient(access_token)
            sheets = GoogleSheetsClient(access_token)
            root = drive.ensure_folder("BNC_BACKUP", "root", "BNC_BACKUP")
            master_root = drive.ensure_folder("01_MASTER", root["id"], "BNC_BACKUP/01_MASTER")
            for year in sorted({year for year, _ in available_months(snapshot)}):
                year_root = drive.ensure_folder(
                    str(year), master_root["id"], f"BNC_BACKUP/01_MASTER/{year}",
                )
                workbook = drive.ensure_spreadsheet(
                    f"BNC_Master_{year}", year_root["id"],
                    f"BNC_BACKUP/01_MASTER/{year}/BNC_Master_{year}",
                )
                sheets.replace_tabs(workbook["id"], build_yearly_master(snapshot, year, {}))
            users_root = drive.ensure_folder("03_USERS", root["id"], "BNC_BACKUP/03_USERS")
            current_root = drive.ensure_folder(
                "00_CURRENT", users_root["id"], "BNC_BACKUP/03_USERS/00_CURRENT",
            )
            users_sheet = drive.ensure_spreadsheet(
                "BNC_Current_Users", current_root["id"],
                "BNC_BACKUP/03_USERS/00_CURRENT/BNC_Current_Users",
            )
            sheets.replace_tabs(users_sheet["id"], build_current_users(snapshot))
        with SessionLocal() as db, db.begin():
            connection = db.get(GoogleConnection, connection_id)
            if connection:
                connection.root_folder_id = root["id"]
                connection.root_web_link = root.get("webViewLink")
                connection.last_verified_at = datetime.now(UTC)

    @staticmethod
    def _complete(event_ids: list) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as db, db.begin():
            db.execute(update(BackupOutbox).where(BackupOutbox.id.in_(event_ids)).values(
                status="DONE", processed_at=now, lease_until=None,
            ))

    @staticmethod
    def _retry(event_ids: list) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as db, db.begin():
            events = db.scalars(select(BackupOutbox).where(BackupOutbox.id.in_(event_ids))).all()
            for event in events:
                event.status = "FAILED"
                event.lease_until = None
                event.next_retry_at = now + timedelta(seconds=min(3600, 60 * (2 ** event.attempt_count)))

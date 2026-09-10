"""One-job backup worker. External calls happen outside database transactions."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.engines.backup.archive import verify_archive
from app.engines.backup.google_drive import GoogleDriveClient, GoogleDriveError
from app.engines.backup.google_sheets import GoogleSheetsClient
from app.engines.backup.sheets_projection import (
    available_months, build_control_sheet, build_current_users, build_monthly_archive,
    build_yearly_master,
)
from app.models.backup import BackupRun, GoogleConnection
from app.services.backup_snapshot_service import create_local_snapshot
from app.services.google_backup_oauth_service import GoogleBackupOAuthError, GoogleBackupOAuthService


class BackupWorkerService:
    oauth = GoogleBackupOAuthService()

    def process_next(self, staging: Path) -> tuple[str, str] | None:
        run_id = self._claim()
        if run_id is None:
            return None
        try:
            destination = staging.resolve() / str(run_id)
            snapshot = create_local_snapshot(destination, run_id=run_id)
            verify_archive(snapshot)
            final_folder, manifest_file = self._upload(run_id, destination, snapshot)
            manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
            source_cutoff = datetime.fromisoformat(manifest["source_cutoff"].replace("Z", "+00:00"))
            self._finish(run_id, "SUCCEEDED", final_folder, manifest_file, source_cutoff)
            status = "SUCCEEDED"
        except Exception as exc:
            # Store only a bounded class code. Provider messages may contain private data.
            self._fail(run_id, type(exc).__name__[:80])
            status = "FAILED"
        return str(run_id), status

    @staticmethod
    def _claim():
        with SessionLocal() as db, db.begin():
            run = db.scalar(
                select(BackupRun).where(BackupRun.status == "PENDING")
                .order_by(BackupRun.created_at).with_for_update(skip_locked=True).limit(1)
            )
            if not run:
                return None
            run.status = "RUNNING"
            run.attempt_count += 1
            run.started_at = datetime.now(UTC)
            run.error_code = None
            return run.id

    def _access_token(self, connection: GoogleConnection) -> str:
        return self.oauth.access_token(connection)

    def _upload(self, run_id, destination: Path, snapshot: Path) -> tuple[str, str]:
        with SessionLocal() as db:
            connection = db.scalar(select(GoogleConnection).where(
                GoogleConnection.purpose == "DRIVE_BACKUP",
                GoogleConnection.status == "ACTIVE",
            ))
            if not connection:
                raise GoogleBackupOAuthError("Google Drive is not connected")
            access_token = self._access_token(connection)
            connection_id = connection.id
        drive = GoogleDriveClient(access_token)
        sheets = GoogleSheetsClient(access_token)
        root = drive.ensure_folder("BNC_BACKUP", "root", "BNC_BACKUP")
        folder_ids = {"BNC_BACKUP": root["id"]}
        relative_root = snapshot.relative_to(destination).as_posix()
        current_path = "BNC_BACKUP"
        current_id = root["id"]
        current_folder = root
        for part in relative_root.split("/")[1:]:
            current_path = f"{current_path}/{part}"
            folder = drive.ensure_folder(part, current_id, current_path)
            current_folder = folder
            current_id = folder["id"]
            folder_ids[current_path] = current_id
        manifest_file_id = ""
        evidence_links = {}
        for source in sorted(path for path in snapshot.rglob("*") if path.is_file()):
            relative = source.relative_to(destination).as_posix()
            parent_path = source.parent.relative_to(destination).as_posix()
            parent_id = folder_ids.get(parent_path)
            if not parent_id:
                current = root["id"]
                built = "BNC_BACKUP"
                for part in parent_path.split("/")[1:]:
                    built = f"{built}/{part}"
                    if built not in folder_ids:
                        folder_ids[built] = drive.ensure_folder(part, current, built)["id"]
                    current = folder_ids[built]
                parent_id = current
            uploaded = drive.ensure_file(source, parent_id, relative, str(run_id))
            if source.name == "manifest.json":
                manifest_file_id = uploaded["id"]
            if source.parent.name == "evidence":
                evidence_links[source.stem] = uploaded.get("webViewLink", "")
        if not manifest_file_id:
            raise GoogleDriveError("Backup manifest was not uploaded")
        months = available_months(snapshot)
        master_root = drive.ensure_folder("01_MASTER", root["id"], "BNC_BACKUP/01_MASTER")
        for year in sorted({year for year, _ in months}):
            master_year = drive.ensure_folder(str(year), master_root["id"], f"BNC_BACKUP/01_MASTER/{year}")
            master = drive.ensure_spreadsheet(
                f"BNC_Master_{year}", master_year["id"], f"BNC_BACKUP/01_MASTER/{year}/BNC_Master_{year}",
            )
            sheets.replace_tabs(master["id"], build_yearly_master(snapshot, year, evidence_links))
        users_root = drive.ensure_folder("03_USERS", root["id"], "BNC_BACKUP/03_USERS")
        users_current = drive.ensure_folder("00_CURRENT", users_root["id"], "BNC_BACKUP/03_USERS/00_CURRENT")
        users_sheet = drive.ensure_spreadsheet(
            "BNC_Current_Users", users_current["id"], "BNC_BACKUP/03_USERS/00_CURRENT/BNC_Current_Users",
        )
        sheets.replace_tabs(users_sheet["id"], build_current_users(snapshot))
        archive_root = drive.ensure_folder("02_ARCHIVE", root["id"], "BNC_BACKUP/02_ARCHIVE")
        archive_years = {}
        for archive_year, archive_month in months:
            if archive_year not in archive_years:
                archive_years[archive_year] = drive.ensure_folder(
                    str(archive_year), archive_root["id"], f"BNC_BACKUP/02_ARCHIVE/{archive_year}",
                )["id"]
            month_name = datetime(archive_year, archive_month, 1).strftime("%B")
            folder_name = f"{archive_month:02d}_{month_name}"
            month_path = f"BNC_BACKUP/02_ARCHIVE/{archive_year}/{folder_name}"
            month_folder = drive.ensure_folder(
                folder_name, archive_years[archive_year], month_path,
            )
            for child in ("01_PAYMENT_EVIDENCE", "02_EXPENSE_RECEIPTS", "03_OTHER_DOCUMENTS", "99_RECOVERY"):
                drive.ensure_folder(child, month_folder["id"], f"{month_path}/{child}")
            monthly_sheet = drive.ensure_spreadsheet(
                f"BNC_{archive_year}-{archive_month:02d}", month_folder["id"],
                f"{month_path}/BNC_{archive_year}-{archive_month:02d}",
            )
            sheets.replace_tabs(
                monthly_sheet["id"],
                build_monthly_archive(snapshot, archive_year, archive_month, evidence_links, str(run_id)),
            )
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        with SessionLocal() as db:
            runs = [{
                "id": str(item.id), "run_type": item.run_type, "trigger_type": item.trigger_type,
                "status": item.status, "attempt_count": item.attempt_count,
                "created_at": item.created_at.isoformat(),
                "completed_at": item.completed_at.isoformat() if item.completed_at else "",
                "error_code": item.error_code or "",
            } for item in db.scalars(
                select(BackupRun).order_by(BackupRun.created_at.desc()).limit(100)
            ).all()]
        control_root = drive.ensure_folder("00_CONTROL", root["id"], "BNC_BACKUP/00_CONTROL")
        control = drive.ensure_spreadsheet(
            "BNC_Backup_Control", control_root["id"], "BNC_BACKUP/00_CONTROL/BNC_Backup_Control",
        )
        sheets.replace_tabs(
            control["id"], build_control_sheet(
                manifest, runs, str(run_id), current_folder.get("webViewLink", ""),
            ),
        )
        with SessionLocal() as db, db.begin():
            connection = db.get(GoogleConnection, connection_id)
            if connection:
                connection.root_folder_id = root["id"]
                connection.root_web_link = root.get("webViewLink")
                connection.last_verified_at = datetime.now(UTC)
        return current_id, manifest_file_id

    @staticmethod
    def _finish(run_id, status: str, folder_id: str, manifest_file_id: str, source_cutoff) -> None:
        from app.models.backup import BackupOutbox

        with SessionLocal() as db, db.begin():
            run = db.get(BackupRun, run_id)
            if run:
                run.status = status
                run.drive_folder_id = folder_id
                run.manifest_file_id = manifest_file_id
                run.source_cutoff = source_cutoff
                run.completed_at = datetime.now(UTC)
            db.execute(update(BackupOutbox).where(
                BackupOutbox.created_at <= source_cutoff,
                BackupOutbox.status.in_(("PENDING", "FAILED")),
            ).values(status="DONE", processed_at=datetime.now(UTC), lease_until=None))

    @staticmethod
    def _fail(run_id, error_code: str) -> None:
        with SessionLocal() as db, db.begin():
            run = db.get(BackupRun, run_id)
            if run:
                run.status = "FAILED"
                run.error_code = error_code
                run.completed_at = datetime.now(UTC)

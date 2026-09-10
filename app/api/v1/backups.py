from urllib.parse import urlencode
from pathlib import Path
from tempfile import gettempdir

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.config.settings import get_settings
from app.constants.permissions import SETTINGS_EDIT
from app.db.session import get_db
from app.models.backup import BackupRun, GoogleConnection
from app.models.identity import User
from app.schemas.backups import BackupRunListOutput, BackupRunOutput, GoogleAuthorizationOutput, GoogleBackupStatusOutput
from app.services.audit_service import AuditService
from app.services.google_backup_oauth_service import (
    GoogleBackupOAuthError,
    GoogleBackupOAuthService,
)
from app.services.backup_worker_service import BackupWorkerService

router = APIRouter(prefix="/admin/backups", tags=["admin backups"])
service = GoogleBackupOAuthService()
audit = AuditService()


def run_output(run: BackupRun) -> BackupRunOutput:
    return BackupRunOutput(
        id=str(run.id), run_type=run.run_type, trigger_type=run.trigger_type,
        status=run.status, attempt_count=run.attempt_count, error_code=run.error_code,
        created_at=run.created_at, started_at=run.started_at, completed_at=run.completed_at,
        source_cutoff=run.source_cutoff,
    )


def process_queued_backup() -> None:
    staging = Path(gettempdir()) / "bnc-backup-staging"
    BackupWorkerService().process_next(staging)


@router.get("/status", response_model=GoogleBackupStatusOutput)
def backup_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> GoogleBackupStatusOutput:
    return service.status(db)


@router.post("/runs", response_model=BackupRunOutput, status_code=202)
def queue_manual_backup(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> BackupRunOutput:
    connection = db.scalar(select(GoogleConnection).where(
        GoogleConnection.purpose == "DRIVE_BACKUP", GoogleConnection.status == "ACTIVE"
    ))
    if not connection:
        raise HTTPException(status_code=409, detail="Connect Google Drive before starting a backup")
    already_queued = db.scalar(select(BackupRun).where(
        BackupRun.status.in_(("PENDING", "RUNNING"))
    ).order_by(BackupRun.created_at.desc()).limit(1))
    if already_queued:
        if already_queued.status == "PENDING":
            background_tasks.add_task(process_queued_backup)
        return run_output(already_queued)
    run = BackupRun(run_type="MANUAL", trigger_type="ADMIN", requested_by=actor.id)
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        active = db.scalar(select(BackupRun).where(
            BackupRun.status.in_(("PENDING", "RUNNING"))
        ).order_by(BackupRun.created_at.desc()).limit(1))
        if active:
            return run_output(active)
        raise
    audit.record(
        db, actor_user_id=actor.id, action="backup.run_queued",
        entity_type="backup_runs", entity_id=run.id,
        after_data={"run_type": run.run_type, "trigger_type": run.trigger_type},
    )
    db.commit()
    db.refresh(run)
    background_tasks.add_task(process_queued_backup)
    return run_output(run)


@router.get("/runs", response_model=BackupRunListOutput)
def list_backup_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> BackupRunListOutput:
    runs = db.scalars(select(BackupRun).order_by(BackupRun.created_at.desc()).limit(limit)).all()
    return BackupRunListOutput(items=[run_output(run) for run in runs])


@router.post("/google/authorization", response_model=GoogleAuthorizationOutput)
def google_authorization(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> GoogleAuthorizationOutput:
    try:
        url, expires_at = service.start(db, actor)
    except GoogleBackupOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return GoogleAuthorizationOutput(authorization_url=url, expires_at=expires_at)


@router.get("/google/callback", include_in_schema=False)
def google_callback(
    state: str = Query(min_length=20, max_length=500),
    code: str | None = Query(default=None, min_length=5, max_length=4096),
    error: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    result = "connected"
    if error or not code:
        result = "denied"
    else:
        try:
            service.complete(db, state, code)
        except GoogleBackupOAuthError:
            result = "failed"
    query = urlencode({"google_backup": result})
    return RedirectResponse(f"{get_settings().frontend_url.rstrip('/')}/admin?{query}", status_code=303)

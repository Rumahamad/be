from datetime import datetime

from pydantic import BaseModel, Field


class GoogleAuthorizationOutput(BaseModel):
    authorization_url: str
    expires_at: datetime


class GoogleBackupStatusOutput(BaseModel):
    configured: bool
    connected: bool
    account_email: str | None = None
    status: str | None = None
    granted_scopes: list[str] = Field(default_factory=list)
    last_verified_at: datetime | None = None
    latest_run_status: str | None = None
    latest_run_started_at: datetime | None = None
    latest_run_completed_at: datetime | None = None
    latest_successful_cutoff: datetime | None = None
    pending_sheet_changes: int = 0
    last_sheet_sync_at: datetime | None = None
    latest_run_error_code: str | None = None
    root_web_link: str | None = None


class BackupRunOutput(BaseModel):
    id: str
    run_type: str
    trigger_type: str
    status: str
    attempt_count: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    source_cutoff: datetime | None


class BackupRunListOutput(BaseModel):
    items: list[BackupRunOutput]

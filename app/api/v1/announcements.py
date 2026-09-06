from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_permission
from app.constants.permissions import ANNOUNCEMENT_MANAGE
from app.db.session import get_db
from app.handlers.announcements import AnnouncementHandler
from app.jobs.push_notifications import process_push_outbox
from app.models.identity import User
from app.schemas.announcements import (
    AnnouncementListOutput,
    AnnouncementOutput,
    CreateAnnouncementInput,
)

router = APIRouter(prefix="/announcements", tags=["announcements"])
handler = AnnouncementHandler()


@router.get("", response_model=AnnouncementListOutput)
def list_announcements(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnnouncementListOutput:
    return handler.list(db, user, offset=offset, limit=limit)


@router.post("", response_model=AnnouncementOutput, status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: CreateAnnouncementInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(ANNOUNCEMENT_MANAGE)),
) -> AnnouncementOutput:
    announcement = handler.create(db, user, payload)
    background_tasks.add_task(process_push_outbox)
    return announcement


@router.post("/{announcement_id}/read", response_model=AnnouncementOutput)
def mark_announcement_read(
    announcement_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnnouncementOutput:
    return handler.mark_read(db, user, announcement_id)

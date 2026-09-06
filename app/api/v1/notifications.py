from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.db.session import get_db
from app.handlers.announcements import NotificationHandler
from app.models.identity import User
from app.schemas.announcements import (
    NotificationListOutput,
    NotificationOutput,
    NotificationReadAllOutput,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
handler = NotificationHandler()


@router.get("", response_model=NotificationListOutput)
def list_notifications(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> NotificationListOutput:
    return handler.list(db, user, offset=offset, limit=limit)


@router.post("/read-all", response_model=NotificationReadAllOutput)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> NotificationReadAllOutput:
    return handler.mark_all_read(db, user)


@router.post("/{notification_id}/read", response_model=NotificationOutput)
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> NotificationOutput:
    return handler.mark_read(db, user, notification_id)

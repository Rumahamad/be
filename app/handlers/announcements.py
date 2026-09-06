from uuid import UUID

from sqlalchemy.orm import Session

from app.models.announcements import Announcement, Notification
from app.models.identity import User
from app.schemas.announcements import (
    AnnouncementListOutput,
    AnnouncementOutput,
    CreateAnnouncementInput,
    NotificationListOutput,
    NotificationOutput,
    NotificationReadAllOutput,
)
from app.services.announcement_service import AnnouncementService, NotificationService


def announcement_output(announcement: Announcement, *, is_read: bool) -> AnnouncementOutput:
    return AnnouncementOutput(
        id=announcement.id,
        title=announcement.title,
        body=announcement.body,
        priority=announcement.priority,
        status=announcement.status,
        pinned=announcement.pinned,
        publish_at=announcement.publish_at,
        expire_at=announcement.expire_at,
        created_by=announcement.created_by,
        is_read=is_read,
        created_at=announcement.created_at,
    )


def notification_output(notification: Notification) -> NotificationOutput:
    return NotificationOutput(
        id=notification.id,
        event_type=notification.event_type,
        title=notification.title,
        message=notification.message,
        reference_type=notification.reference_type,
        reference_id=notification.reference_id,
        is_read=notification.is_read,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


class AnnouncementHandler:
    def __init__(self) -> None:
        self.service = AnnouncementService()

    def create(
        self, db: Session, actor: User, payload: CreateAnnouncementInput
    ) -> AnnouncementOutput:
        announcement = self.service.create(db, actor, payload)
        db.commit()
        db.refresh(announcement)
        return announcement_output(announcement, is_read=False)

    def list(
        self, db: Session, user: User, *, offset: int, limit: int
    ) -> AnnouncementListOutput:
        rows, total = self.service.list_visible(db, user, offset=offset, limit=limit)
        return AnnouncementListOutput(
            items=[
                announcement_output(announcement, is_read=read_user_id is not None)
                for announcement, read_user_id in rows
            ],
            total=total,
        )

    def mark_read(
        self, db: Session, user: User, announcement_id: UUID
    ) -> AnnouncementOutput:
        announcement = self.service.mark_read(db, user, announcement_id)
        db.commit()
        return announcement_output(announcement, is_read=True)


class NotificationHandler:
    def __init__(self) -> None:
        self.service = NotificationService()

    def list(
        self, db: Session, user: User, *, offset: int, limit: int
    ) -> NotificationListOutput:
        items, total, unread_count = self.service.list(
            db, user, offset=offset, limit=limit
        )
        return NotificationListOutput(
            items=[notification_output(item) for item in items],
            total=total,
            unread_count=unread_count,
        )

    def mark_read(
        self, db: Session, user: User, notification_id: UUID
    ) -> NotificationOutput:
        notification = self.service.mark_read(db, user, notification_id)
        db.commit()
        return notification_output(notification)

    def mark_all_read(self, db: Session, user: User) -> NotificationReadAllOutput:
        updated_count = self.service.mark_all_read(db, user)
        db.commit()
        return NotificationReadAllOutput(updated_count=updated_count)

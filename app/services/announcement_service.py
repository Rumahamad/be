from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.announcements import (
    Announcement,
    AnnouncementRead,
    AnnouncementTarget,
    Notification,
)
from app.models.communications import NotificationOutbox
from app.models.enums import UserStatus
from app.models.identity import Permission, RolePermission, User
from app.repositories.announcements import AnnouncementRepository
from app.schemas.announcements import CreateAnnouncementInput
from app.services.audit_service import AuditService


class AnnouncementService:
    def __init__(self) -> None:
        self.repository = AnnouncementRepository()
        self.audit = AuditService()

    def create(
        self, db: Session, actor: User, payload: CreateAnnouncementInput
    ) -> Announcement:
        now = datetime.now(UTC)
        publish_at = payload.publish_at or now
        if payload.expire_at and payload.expire_at <= publish_at:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expire_at must be later than publish_at",
            )
        announcement_status = "SCHEDULED" if publish_at > now else "PUBLISHED"
        for target_type in ("ROLE", "GROUP", "USER"):
            ids = {
                target.target_id
                for target in payload.targets
                if target.target_type == target_type and target.target_id is not None
            }
            if not self.repository.validate_target_ids(db, target_type, ids):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown {target_type.lower()} announcement target",
                )
        announcement = Announcement(
            title=payload.title.strip(),
            body=payload.body.strip(),
            priority=payload.priority,
            status=announcement_status,
            pinned=payload.pinned,
            publish_at=publish_at,
            expire_at=payload.expire_at,
            created_by=actor.id,
        )
        db.add(announcement)
        db.flush()
        targets = [
            AnnouncementTarget(
                announcement_id=announcement.id,
                target_type=target.target_type,
                target_id=target.target_id,
            )
            for target in payload.targets
        ]
        db.add_all(targets)
        recipient_count = self._create_notifications(db, announcement, targets) if announcement_status == "PUBLISHED" else 0
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="announcement.created",
            entity_type="announcement",
            entity_id=announcement.id,
            after_data={
                "title": announcement.title,
                "priority": announcement.priority,
                "status": announcement.status,
                "recipient_count": recipient_count,
            },
        )
        return announcement

    def _create_notifications(
        self,
        db: Session,
        announcement: Announcement,
        targets: list[AnnouncementTarget],
    ) -> int:
        recipient_ids = self.repository.recipient_ids(db, targets)
        NotificationService().create_for_users(
            db,
            user_ids=recipient_ids,
            event_type="ANNOUNCEMENT_PUBLISHED",
            title=announcement.title,
            message=announcement.body,
            reference_type="announcement",
            reference_id=announcement.id,
            push_url="/?section=Announcements",
        )
        return len(recipient_ids)

    def publish_due(self, db: Session, *, limit: int = 100) -> int:
        now = datetime.now(UTC)
        announcements = self.repository.due_scheduled(db, now=now, limit=limit)
        for announcement in announcements:
            announcement.status = "PUBLISHED"
            targets = self.repository.targets_for(db, announcement.id)
            recipient_count = self._create_notifications(db, announcement, targets)
            self.audit.record(
                db,
                actor_user_id=announcement.created_by,
                action="announcement.published",
                entity_type="announcement",
                entity_id=announcement.id,
                after_data={"recipient_count": recipient_count, "scheduled": True},
            )
        return len(announcements)

    def list_visible(self, db: Session, user: User, *, offset: int, limit: int):
        return self.repository.list_visible(
            db, user, now=datetime.now(UTC), offset=offset, limit=limit
        )

    def mark_read(self, db: Session, user: User, announcement_id: UUID) -> Announcement:
        announcement = self.repository.visible_by_id(
            db, user, announcement_id, now=datetime.now(UTC)
        )
        if not announcement:
            raise HTTPException(status_code=404, detail="Announcement not found")
        existing = db.get(AnnouncementRead, (announcement_id, user.id))
        if not existing:
            db.add(AnnouncementRead(announcement_id=announcement_id, user_id=user.id))
        notifications = db.scalars(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.reference_type == "announcement",
                Notification.reference_id == announcement_id,
                Notification.is_read.is_(False),
            )
        ).all()
        now = datetime.now(UTC)
        for notification in notifications:
            notification.is_read = True
            notification.read_at = now
        return announcement


class NotificationService:
    def __init__(self) -> None:
        self.repository = AnnouncementRepository()

    def list(self, db: Session, user: User, *, offset: int, limit: int):
        return self.repository.list_notifications(db, user.id, offset=offset, limit=limit)

    def users_with_permission(self, db: Session, permission_code: str) -> list[UUID]:
        return list(
            db.scalars(
                select(User.id)
                .join(RolePermission, RolePermission.role_id == User.role_id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(
                    User.status == UserStatus.ACTIVE,
                    Permission.code == permission_code,
                    RolePermission.allowed.is_(True),
                )
                .distinct()
            ).all()
        )

    def create_for_users(
        self,
        db: Session,
        *,
        user_ids: list[UUID],
        event_type: str,
        title: str,
        message: str,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
        email_payload: dict | None = None,
        push_url: str = "/",
        push_payload: dict | None = None,
    ) -> None:
        for user_id in set(user_ids):
            db.add(
                Notification(
                    user_id=user_id,
                    event_type=event_type,
                    title=title,
                    message=message,
                    reference_type=reference_type,
                    reference_id=reference_id,
                )
            )
            # EMAIL channel
            db.add(
                NotificationOutbox(
                    event_type=event_type,
                    recipient_user_id=user_id,
                    channel="EMAIL",
                    template_key=event_type.lower(),
                    payload={
                        "title": title,
                        "message": message,
                        **(email_payload or {}),
                    },
                    status="PENDING",
                )
            )
            # PUSH channel
            db.add(
                NotificationOutbox(
                    event_type=event_type,
                    recipient_user_id=user_id,
                    channel="PUSH",
                    template_key=event_type.lower(),
                    payload={
                        "title": title,
                        "message": message,
                        "url": push_url,
                        "tag": event_type.lower(),
                        **(push_payload or {}),
                    },
                    status="PENDING",
                )
            )

    def mark_read(self, db: Session, user: User, notification_id: UUID) -> Notification:
        notification = db.scalar(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user.id
            )
        )
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(UTC)
        return notification

    def mark_all_read(self, db: Session, user: User) -> int:
        result = db.execute(
            update(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        return int(result.rowcount or 0)

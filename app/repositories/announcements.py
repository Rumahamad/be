from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.announcements import (
    Announcement,
    AnnouncementRead,
    AnnouncementTarget,
    Notification,
)
from app.models.enums import UserStatus
from app.models.identity import Group, Role, User, UserGroup


class AnnouncementRepository:
    def audience_condition(self, user: User):
        group_ids = select(UserGroup.group_id).where(UserGroup.user_id == user.id)
        return or_(
            AnnouncementTarget.target_type == "ALL",
            and_(
                AnnouncementTarget.target_type == "USER",
                AnnouncementTarget.target_id == user.id,
            ),
            and_(
                AnnouncementTarget.target_type == "ROLE",
                AnnouncementTarget.target_id == user.role_id,
            ),
            and_(
                AnnouncementTarget.target_type == "GROUP",
                AnnouncementTarget.target_id.in_(group_ids),
            ),
        )

    def list_visible(
        self, db: Session, user: User, *, now: datetime, offset: int, limit: int
    ) -> tuple[list[tuple[Announcement, UUID | None]], int]:
        audience = self.audience_condition(user)
        visible = and_(
            Announcement.status == "PUBLISHED",
            Announcement.publish_at <= now,
            or_(Announcement.expire_at.is_(None), Announcement.expire_at > now),
            audience,
        )
        base = select(Announcement.id).join(AnnouncementTarget).where(visible).distinct().subquery()
        total = db.scalar(select(func.count()).select_from(base)) or 0
        rows = db.execute(
            select(Announcement, AnnouncementRead.user_id)
            .join(base, base.c.id == Announcement.id)
            .outerjoin(
                AnnouncementRead,
                and_(
                    AnnouncementRead.announcement_id == Announcement.id,
                    AnnouncementRead.user_id == user.id,
                ),
            )
            .order_by(Announcement.pinned.desc(), Announcement.publish_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return list(rows), int(total)

    def visible_by_id(
        self, db: Session, user: User, announcement_id: UUID, *, now: datetime
    ) -> Announcement | None:
        return db.scalar(
            select(Announcement)
            .join(AnnouncementTarget)
            .where(
                Announcement.id == announcement_id,
                Announcement.status == "PUBLISHED",
                Announcement.publish_at <= now,
                or_(Announcement.expire_at.is_(None), Announcement.expire_at > now),
                self.audience_condition(user),
            )
        )

    def recipient_ids(
        self, db: Session, targets: list[AnnouncementTarget]
    ) -> list[UUID]:
        clauses = []
        for target in targets:
            if target.target_type == "ALL":
                clauses = [User.id.is_not(None)]
                break
            if target.target_type == "USER":
                clauses.append(User.id == target.target_id)
            elif target.target_type == "ROLE":
                clauses.append(User.role_id == target.target_id)
            elif target.target_type == "GROUP":
                clauses.append(
                    User.id.in_(
                        select(UserGroup.user_id).where(UserGroup.group_id == target.target_id)
                    )
                )
        if not clauses:
            return []
        return list(
            db.scalars(
                select(User.id)
                .where(User.status == UserStatus.ACTIVE, or_(*clauses))
                .distinct()
            ).all()
        )

    def targets_for(self, db: Session, announcement_id: UUID) -> list[AnnouncementTarget]:
        return list(
            db.scalars(
                select(AnnouncementTarget).where(
                    AnnouncementTarget.announcement_id == announcement_id
                )
            ).all()
        )

    def due_scheduled(self, db: Session, *, now: datetime, limit: int) -> list[Announcement]:
        return list(
            db.scalars(
                select(Announcement)
                .where(Announcement.status == "SCHEDULED", Announcement.publish_at <= now)
                .order_by(Announcement.publish_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )

    def validate_target_ids(self, db: Session, target_type: str, target_ids: set[UUID]) -> bool:
        if not target_ids:
            return True
        model = {"ROLE": Role, "GROUP": Group, "USER": User}[target_type]
        found = set(db.scalars(select(model.id).where(model.id.in_(target_ids))).all())
        return found == target_ids

    def list_notifications(
        self, db: Session, user_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Notification], int, int]:
        total = db.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == user_id)
        ) or 0
        unread = db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        ) or 0
        items = db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return list(items), int(total), int(unread)

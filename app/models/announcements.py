import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, utcnow


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    status: Mapped[str] = mapped_column(String(20), default="PUBLISHED")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    __table_args__ = (Index("ix_announcements_visibility", "status", "publish_at", "expire_at"),)


class AnnouncementTarget(Base):
    __tablename__ = "announcement_targets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("announcements.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        UniqueConstraint(
            "announcement_id", "target_type", "target_id", name="uq_announcement_target"
        ),
    )


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("announcements.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    reference_type: Mapped[str | None] = mapped_column(String(60))
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "is_read", "created_at"),)

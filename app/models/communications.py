import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import utcnow


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receipt_no: Mapped[str] = mapped_column(String(40), unique=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), unique=True, index=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id"))
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str] = mapped_column(String(30), default="PENDING_GENERATION")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20), default="EMAIL")
    template_key: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_notification_outbox_due", "status", "next_retry_at", "created_at"),
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_outbox.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    recipient: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt_no: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("outbox_id", "attempt_no", name="uq_notification_delivery_attempt"),
    )


class ContributionReminderDelivery(Base):
    __tablename__ = "contribution_reminder_deliveries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    days_before: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "year",
            "month",
            "days_before",
            name="uq_contribution_reminder_delivery",
        ),
    )

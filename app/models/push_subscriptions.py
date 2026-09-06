import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import utcnow


class PushSubscription(Base):
    """Stores a browser Web Push subscription endpoint for a user."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The full Push API subscription endpoint URL
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    # p256dh public key (base64url)
    p256dh: Mapped[str] = mapped_column(String(256), nullable=False)
    # auth secret (base64url)
    auth: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("user_id", "endpoint", name="uq_push_subscription_user_endpoint"),
    )

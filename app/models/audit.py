import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import utcnow


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    before_data: Mapped[dict | None] = mapped_column(JSONB)
    after_data: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

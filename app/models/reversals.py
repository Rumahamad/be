import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import utcnow


class PaymentReversal(Base):
    __tablename__ = "payment_reversals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), unique=True, index=True
    )
    original_fund_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fund_entries.id"), unique=True
    )
    reversal_fund_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fund_entries.id"), unique=True
    )
    reason: Mapped[str] = mapped_column(Text)
    reversed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reversed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

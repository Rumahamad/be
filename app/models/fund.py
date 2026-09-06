import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.enums import LedgerDirection
from app.models.mixins import TimestampMixin, utcnow


class FundAccount(Base, TimestampMixin):
    __tablename__ = "fund_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    account_type: Mapped[str] = mapped_column(String(30), default="GENERAL")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FundEntry(Base):
    __tablename__ = "fund_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_no: Mapped[str] = mapped_column(String(40), unique=True)
    fund_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fund_accounts.id")
    )
    entry_date: Mapped[date] = mapped_column(Date)
    direction: Mapped[LedgerDirection] = mapped_column(
        Enum(LedgerDirection, name="ledger_direction")
    )
    entry_type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reference_type: Mapped[str] = mapped_column(String(40))
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str | None] = mapped_column(Text)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fund_entries.id"), unique=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

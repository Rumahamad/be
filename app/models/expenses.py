import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, utcnow


class ExpenseCategory(Base, TimestampMixin):
    __tablename__ = "expense_categories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expense_categories.id", ondelete="RESTRICT"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("id <> parent_id", name="ck_expense_category_not_self"),)


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fund_accounts.id"), index=True
    )
    expense_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expense_categories.id", ondelete="SET NULL"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    payee: Mapped[str | None] = mapped_column(String(200))
    responsible_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    payment_method: Mapped[str | None] = mapped_column(String(50))
    reference_no: Mapped[str | None] = mapped_column(String(120))
    internal_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="POSTED")
    expense_date: Mapped[date] = mapped_column(Date)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ExpenseAttachment(Base):
    __tablename__ = "expense_attachments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    expense_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expenses.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id"), unique=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("expense_id", "file_id", name="uq_expense_attachment_file"),
    )

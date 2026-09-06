import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin


class OrganizationSetting(Base, TimestampMixin):
    __tablename__ = "organization_settings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(30), default="BNC")
    payment_upi_id: Mapped[str | None] = mapped_column(String(150))
    payment_mobile: Mapped[str | None] = mapped_column(String(30))
    payment_qr_path: Mapped[str | None] = mapped_column(String(500))
    whatsapp_group_url: Mapped[str | None] = mapped_column(String(500))
    default_language: Mapped[str] = mapped_column(String(10), default="en")
    default_theme: Mapped[str] = mapped_column(String(50), default="bnc-green")
    expense_visibility: Mapped[str] = mapped_column(String(20), default="SUMMARY")
    expense_visible_fields: Mapped[list[str]] = mapped_column(
        JSONB, default=lambda: ["category", "amount", "expense_date"]
    )
    reminder_days_before_month_end: Mapped[list[int]] = mapped_column(
        JSONB, default=lambda: [5, 1]
    )

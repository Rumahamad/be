from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class CurrentMonthOutput(BaseModel):
    year: int
    month: int
    status: Literal["AVAILABLE", "PENDING", "APPROVED", "REJECTED"]
    amount: Decimal | None = None
    payment_id: str | None = None


class RecentContributionOutput(BaseModel):
    year: int
    month: int
    amount: Decimal
    status: str


class DashboardOutput(BaseModel):
    display_name: str
    current_month: CurrentMonthOutput
    current_year_total: Decimal
    lifetime_total: Decimal
    contributed_months_current_year: int
    elapsed_months_current_year: int
    recent_contributions: list[RecentContributionOutput]


class PaymentSettingsOutput(BaseModel):
    organization_name: str
    short_name: str
    upi_id: str | None
    mobile: str | None
    qr_url: str | None
    whatsapp_group_url: str | None
    expense_visibility: str
    expense_visible_fields: list[str]

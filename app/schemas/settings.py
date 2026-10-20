from typing import Literal

from pydantic import BaseModel, Field, field_validator

EXPENSE_VISIBLE_FIELDS = {
    "category",
    "amount",
    "expense_date",
    "description",
    "payee",
    "responsible_member",
    "payment_method",
    "reference_no",
    "attachments",
}
EXPENSE_SUMMARY_FIELDS = {"category", "amount", "expense_date"}


class OrganizationSettingsOutput(BaseModel):
    organization_name: str
    short_name: str
    payment_upi_id: str | None
    payment_mobile: str | None
    whatsapp_group_url: str | None
    default_language: Literal["en", "bn", "ur", "pr"]
    default_theme: Literal["bnc-green", "night"]
    expense_visibility: Literal["HIDDEN", "SUMMARY", "DETAILS"]
    expense_visible_fields: list[str]
    reminder_days_before_month_end: list[int]


class UpdateOrganizationSettingsInput(BaseModel):
    organization_name: str | None = Field(default=None, min_length=2, max_length=200)
    short_name: str | None = Field(default=None, min_length=2, max_length=30)
    payment_upi_id: str | None = Field(default=None, max_length=150)
    payment_mobile: str | None = Field(default=None, max_length=30)
    whatsapp_group_url: str | None = Field(default=None, max_length=500)
    default_language: Literal["en", "bn", "ur", "pr"] | None = None
    default_theme: Literal["bnc-green", "night"] | None = None
    expense_visibility: Literal["HIDDEN", "SUMMARY", "DETAILS"] | None = None
    expense_visible_fields: list[str] | None = Field(default=None, max_length=20)
    reminder_days_before_month_end: list[int] | None = Field(default=None, max_length=10)

    @field_validator("organization_name", "short_name")
    @classmethod
    def required_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip() if value else value

    @field_validator("reminder_days_before_month_end")
    @classmethod
    def valid_reminder_days(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(day < 0 or day > 30 for day in value):
            raise ValueError("Reminder days must be between 0 and 30")
        return sorted(set(value or []), reverse=True) if value is not None else None

    @field_validator("expense_visible_fields")
    @classmethod
    def valid_expense_visible_fields(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(value))
        unknown = set(normalized) - EXPENSE_VISIBLE_FIELDS
        if unknown:
            raise ValueError(f"Unknown expense visibility fields: {', '.join(sorted(unknown))}")
        return list(dict.fromkeys([*normalized, *sorted(EXPENSE_SUMMARY_FIELDS)]))

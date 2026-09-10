from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CreateExpenseCategoryInput(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: UUID | None = None
    sort_order: int = Field(default=0, ge=-10000, le=10000)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name cannot be blank")
        return normalized


class UpdateExpenseCategoryInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=-10000, le=10000)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def required_update_values(self) -> "UpdateExpenseCategoryInput":
        for field in ("name", "sort_order", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field.replace('_', ' ').title()} is required")
        return self


class ExpenseCategoryOutput(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    parent_id: UUID | None
    sort_order: int
    is_active: bool
    created_at: datetime


class CreateExpenseInput(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category_id: UUID | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=3000)
    payee: str | None = Field(default=None, max_length=200)
    responsible_member_id: UUID | None = None
    payment_method: str | None = Field(default=None, max_length=50)
    reference_no: str | None = Field(default=None, max_length=120)
    internal_note: str | None = Field(default=None, max_length=3000)
    expense_date: date | None = None

    @model_validator(mode="after")
    def category_reference(self) -> "CreateExpenseInput":
        if not self.category_id and not self.category:
            raise ValueError("category_id or category is required")
        return self


class ReverseExpenseInput(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Reversal reason must contain at least 3 characters")
        return normalized


class ExpenseOutput(BaseModel):
    id: UUID
    entry_no: str
    category_id: UUID | None
    amount: Decimal
    category: str
    description: str | None
    payee: str | None
    responsible_member_id: UUID | None
    responsible_member_name: str | None
    payment_method: str | None
    reference_no: str | None
    internal_note: str | None
    status: str
    expense_date: date
    created_at: datetime


class ExpenseAttachmentOutput(BaseModel):
    id: UUID
    original_name: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    download_url: str


class ExpenseListOutput(BaseModel):
    items: list[ExpenseOutput]
    total: int

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class FundSummaryOutput(BaseModel):
    account_id: UUID
    account_name: str
    account_code: str
    balance: Decimal
    total_credits: Decimal
    total_debits: Decimal
    entry_count: int


class FundEntryOutput(BaseModel):
    id: UUID
    entry_no: str
    entry_date: date
    direction: str
    entry_type: str
    amount: Decimal
    reference_type: str
    reference_id: UUID
    description: str | None
    reversal_of_id: UUID | None
    created_by: UUID
    created_at: datetime


class FundEntryListOutput(BaseModel):
    items: list[FundEntryOutput]
    total: int


class CreateFundAdjustmentInput(BaseModel):
    direction: Literal["CREDIT", "DEBIT"]
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    description: str = Field(min_length=3, max_length=2000)
    entry_date: date | None = None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Description must contain at least 3 characters")
        return normalized


class ReverseFundEntryInput(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Reversal reason must contain at least 3 characters")
        return normalized

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AllocationInput(BaseModel):
    member_id: UUID
    year: int = Field(ge=2020, le=2200)
    month: int = Field(ge=1, le=12)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class CreatePaymentInput(BaseModel):
    allocations: list[AllocationInput] = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def no_duplicate_member_month(self) -> "CreatePaymentInput":
        keys = {(a.member_id, a.year, a.month) for a in self.allocations}
        if len(keys) != len(self.allocations):
            raise ValueError("Each member and calendar month can appear only once")
        return self


class PaymentOutput(BaseModel):
    id: UUID
    payment_no: str
    status: str
    total_amount: Decimal
    current_revision: int
    submitted_at: datetime | None


class PaymentQueueItem(BaseModel):
    id: UUID
    payment_no: str
    status: str
    total_amount: Decimal
    current_revision: int
    submitted_at: datetime | None
    submitted_by_id: UUID
    submitted_by_name: str
    submitted_by_email: str
    rejection_reason: str | None


class PaymentListOutput(BaseModel):
    items: list[PaymentQueueItem]
    total: int


class PaymentFileOutput(BaseModel):
    id: UUID
    original_name: str
    mime_type: str
    size_bytes: int
    revision_no: int


class RejectPaymentInput(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class ReversePaymentInput(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class ContributionAvailabilityInput(BaseModel):
    member_ids: list[UUID] = Field(min_length=1, max_length=100)
    year_from: int = Field(ge=2020, le=2200)
    year_to: int = Field(ge=2020, le=2200)

    @model_validator(mode="after")
    def valid_year_range(self) -> "ContributionAvailabilityInput":
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("Each member can appear only once")
        if self.year_to < self.year_from:
            raise ValueError("year_to must be greater than or equal to year_from")
        if self.year_to - self.year_from > 10:
            raise ValueError("Availability can cover at most eleven calendar years")
        return self


class ContributionMonthStateOutput(BaseModel):
    member_id: UUID
    year: int
    month: int
    status: Literal["PENDING", "APPROVED", "REJECTED", "REVERSED"]
    amount: Decimal
    payment_id: UUID


class ContributionAvailabilityOutput(BaseModel):
    items: list[ContributionMonthStateOutput]


class PaymentAllocationOutput(BaseModel):
    member_id: UUID
    member_code: str
    member_name: str
    year: int
    month: int
    amount: Decimal


class PaymentReviewOutput(BaseModel):
    revision_no: int
    action: str
    comment: str | None
    reviewed_by: UUID
    reviewer_name: str
    created_at: datetime


class PaymentRevisionAllocationOutput(BaseModel):
    member_id: UUID
    year: int
    month: int
    amount: Decimal


class PaymentRevisionOutput(BaseModel):
    revision_no: int
    total_amount: Decimal
    user_note: str | None
    status_snapshot: str
    created_at: datetime
    allocations: list[PaymentRevisionAllocationOutput]


class ReceiptOutput(BaseModel):
    id: UUID
    receipt_no: str
    status: str
    generated_at: datetime | None


class PaymentReversalOutput(BaseModel):
    id: UUID
    reason: str
    reversed_by: UUID
    reversed_by_name: str
    reversed_at: datetime
    reversal_entry_no: str


class PaymentDetailOutput(BaseModel):
    id: UUID
    payment_no: str
    status: str
    total_amount: Decimal
    current_revision: int
    user_note: str | None
    submitted_at: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    submitted_by_id: UUID
    submitted_by_name: str
    submitted_by_email: str
    allocations: list[PaymentAllocationOutput]
    reviews: list[PaymentReviewOutput]
    revisions: list[PaymentRevisionOutput]
    receipt: ReceiptOutput | None
    reversal: PaymentReversalOutput | None

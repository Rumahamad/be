from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class PaymentReportSummary(BaseModel):
    count: int
    total_amount: Decimal
    approved_amount: Decimal
    pending_amount: Decimal
    rejected_amount: Decimal
    reversed_amount: Decimal


class ExpenseReportSummary(BaseModel):
    count: int
    total_amount: Decimal
    posted_amount: Decimal
    reversed_amount: Decimal


class FundReportSummary(BaseModel):
    entry_count: int
    total_credits: Decimal
    total_debits: Decimal
    balance: Decimal


class ReportSummaryOutput(BaseModel):
    date_from: date | None
    date_to: date | None
    payments: PaymentReportSummary
    expenses: ExpenseReportSummary
    fund: FundReportSummary


class PaymentReportAllocation(BaseModel):
    allocation_id: UUID
    member_code: str
    member_name: str
    contribution_year: int
    contribution_month: int
    allocation_amount: Decimal


class PaymentReportRow(BaseModel):
    payment_id: UUID
    payment_no: str
    status: str
    total_amount: Decimal
    current_revision: int
    submitted_at: datetime | None
    approved_at: datetime | None
    submitted_by_code: str
    submitted_by_name: str
    user_note: str | None
    allocations: list[PaymentReportAllocation]


class ExpenseReportRow(BaseModel):
    expense_id: UUID
    expense_date: date
    status: str
    category: str
    amount: Decimal
    description: str | None
    payee: str | None
    responsible_member_code: str | None
    responsible_member_name: str | None
    payment_method: str | None
    reference_no: str | None
    internal_note: str | None
    fund_account_code: str
    created_by_name: str
    created_at: datetime


class FundReportRow(BaseModel):
    entry_id: UUID
    entry_no: str
    entry_date: date
    direction: str
    entry_type: str
    amount: Decimal
    reference_type: str
    reference_id: UUID
    description: str | None
    reversal_of_id: UUID | None
    fund_account_code: str
    created_by_name: str
    created_at: datetime


class PaymentReportPage(BaseModel):
    items: list[PaymentReportRow]
    total: int
    offset: int
    limit: int


class ExpenseReportPage(BaseModel):
    items: list[ExpenseReportRow]
    total: int
    offset: int
    limit: int


class FundReportPage(BaseModel):
    items: list[FundReportRow]
    total: int
    offset: int
    limit: int

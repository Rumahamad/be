from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field
from uuid import UUID


class PaymentMatchOutput(BaseModel):
    payment_id: UUID
    payment_no: str
    member_name: str
    payment_status: str
    amount: Decimal
    screenshot_status: str
    screenshot_utrs: list[str]
    email_utr: str | None
    email_amount: Decimal | None
    reference_matches: bool | None
    amount_matches: bool | None
    account_matches: bool | None
    email_authenticated: bool | None
    verification_status: str
    reason: str | None


class GmailVerificationStatusOutput(BaseModel):
    can_approve_verified: bool = False
    approval_mode: str = 'DISABLED'
    payments: list[PaymentMatchOutput] = Field(default_factory=list)
    configured: bool
    connected: bool
    account_email: str | None = None
    last_successful_sync_at: datetime | None = None
    last_error_code: str | None = None
    last_credit_error_code: str | None = None
    latest_credit_status: str | None = None
    latest_credit_received_at: datetime | None = None
    pending_payments: int = 0
    unmatched_credits: int = 0
    processed_credits: int = 0
    rejected_credits: int = 0
    review_required_credits: int = 0


class GmailSyncOutput(BaseModel):
    discovered: int
    stored: int
    rejected: int
    matched: int = 0
    auto_approved: int = 0


class OcrTestOutput(BaseModel):
    status: str
    selected_reference_masked: str | None = None
    confidence: Decimal | None = None
    candidate_count: int = 0
    engine: str
    engine_version: str | None = None
    error_code: str | None = None


class VerificationFixtureInput(BaseModel):
    email_body: str
    screenshot_ocr_text: str
    payment_amount: Decimal
    expected_account_last4: str


class VerificationFixtureOutput(BaseModel):
    email_valid: bool
    screenshot_reference_found: bool
    reference_matches: bool
    amount_matches: bool
    account_matches: bool
    would_auto_approve_if_authenticated: bool
    error_codes: list[str]

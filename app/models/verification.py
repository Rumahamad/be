import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, utcnow


class IncomingUpiCredit(Base, TimestampMixin):
    __tablename__ = "incoming_upi_credits"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30), default="HDFC_GMAIL")
    gmail_message_id: Mapped[str] = mapped_column(String(255), unique=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(String(255))
    message_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sender_name: Mapped[str | None] = mapped_column(String(255))
    sender_vpa: Mapped[str | None] = mapped_column(String(255))
    upi_reference: Mapped[str | None] = mapped_column(String(40), unique=True)
    observed_upi_reference: Mapped[str | None] = mapped_column(String(40))
    recipient_account_last4: Mapped[str | None] = mapped_column(String(4))
    email_from: Mapped[str] = mapped_column(String(320))
    email_subject: Mapped[str | None] = mapped_column(String(500))
    sender_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    spf_pass: Mapped[bool | None] = mapped_column(Boolean)
    dkim_pass: Mapped[bool | None] = mapped_column(Boolean)
    recipient_account_matches: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    parse_error_code: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str] = mapped_column(String(30))
    authentication_evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    matched_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"), unique=True
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentProofExtraction(Base):
    __tablename__ = "payment_proof_extractions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
    proof_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    payment_revision: Mapped[int] = mapped_column()
    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    reference_candidates: Mapped[list] = mapped_column(JSONB, default=list)
    selected_upi_reference: Mapped[str | None] = mapped_column(String(40), index=True)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    ocr_engine: Mapped[str] = mapped_column(String(40))
    ocr_engine_version: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("payment_id", "proof_file_id", name="uq_proof_extraction_payment_file"),
    )


class PaymentUtrClaim(Base):
    __tablename__ = 'payment_utr_claims'
    reference: Mapped[str] = mapped_column(String(40), primary_key=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('payments.id'), index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentVerificationEvent(Base):
    __tablename__ = "payment_verification_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    incoming_credit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incoming_upi_credits.id", ondelete="SET NULL")
    )
    upi_reference_masked: Mapped[str | None] = mapped_column(String(40))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

"""Add payment verification and HDFC Gmail ingestion foundation.

Revision ID: 0019_payment_verification
Revises: 0018_backup_schema_repair
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0019_payment_verification"
down_revision = "0018_backup_schema_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("google_connections", sa.Column("last_sync_at", sa.DateTime(timezone=True)))
    op.add_column("google_connections", sa.Column("last_sync_error_code", sa.String(80)))
    op.add_column("payments", sa.Column(
        "verification_status", sa.String(30), nullable=False, server_default="NOT_STARTED",
    ))
    op.add_column("payments", sa.Column("verification_method", sa.String(20)))
    op.add_column("payments", sa.Column("auto_verified_at", sa.DateTime(timezone=True)))
    op.add_column("payments", sa.Column("auto_verified_reference", sa.String(40)))
    op.add_column("payments", sa.Column("verification_error_code", sa.String(80)))

    op.create_table(
        "incoming_upi_credits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="HDFC_GMAIL"),
        sa.Column("gmail_message_id", sa.String(255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(255)),
        sa.Column("message_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("transaction_at", sa.DateTime(timezone=True)),
        sa.Column("sender_name", sa.String(255)),
        sa.Column("sender_vpa", sa.String(255)),
        sa.Column("upi_reference", sa.String(40)),
        sa.Column("recipient_account_last4", sa.String(4)),
        sa.Column("email_from", sa.String(320), nullable=False),
        sa.Column("email_subject", sa.String(500)),
        sa.Column("sender_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spf_pass", sa.Boolean()),
        sa.Column("dkim_pass", sa.Boolean()),
        sa.Column("recipient_account_matches", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("parse_status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("parse_error_code", sa.String(80)),
        sa.Column("parser_version", sa.String(30), nullable=False),
        sa.Column("matched_payment_id", postgresql.UUID(as_uuid=True)),
        sa.Column("matched_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["matched_payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("gmail_message_id", name="uq_incoming_upi_credit_gmail_message"),
        sa.UniqueConstraint("upi_reference", name="uq_incoming_upi_credit_reference"),
        sa.UniqueConstraint("matched_payment_id", name="uq_incoming_upi_credit_payment"),
    )
    op.create_index("ix_incoming_upi_credit_status", "incoming_upi_credits", ["parse_status", "created_at"])

    op.create_table(
        "payment_proof_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proof_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_revision", sa.Integer(), nullable=False),
        sa.Column("raw_ocr_text", sa.Text()),
        sa.Column("reference_candidates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("selected_upi_reference", sa.String(40)),
        sa.Column("ocr_confidence", sa.Numeric(5, 4)),
        sa.Column("ocr_engine", sa.String(40), nullable=False),
        sa.Column("ocr_engine_version", sa.String(40)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proof_file_id"], ["files.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("payment_id", "proof_file_id", name="uq_proof_extraction_payment_file"),
    )
    op.create_index("ix_proof_extraction_payment", "payment_proof_extractions", ["payment_id"])
    op.create_index("ix_proof_extraction_file", "payment_proof_extractions", ["proof_file_id"])
    op.create_index("ix_proof_extraction_reference", "payment_proof_extractions", ["selected_upi_reference"])

    op.create_table(
        "payment_verification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("incoming_credit_id", postgresql.UUID(as_uuid=True)),
        sa.Column("upi_reference_masked", sa.String(40)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["incoming_credit_id"], ["incoming_upi_credits.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_verification_event_payment", "payment_verification_events", ["payment_id", "created_at"])
    op.create_index("ix_verification_event_type", "payment_verification_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("payment_verification_events")
    op.drop_table("payment_proof_extractions")
    op.drop_table("incoming_upi_credits")
    op.drop_column("payments", "verification_error_code")
    op.drop_column("payments", "auto_verified_reference")
    op.drop_column("payments", "auto_verified_at")
    op.drop_column("payments", "verification_method")
    op.drop_column("payments", "verification_status")
    op.drop_column("google_connections", "last_sync_error_code")
    op.drop_column("google_connections", "last_sync_at")

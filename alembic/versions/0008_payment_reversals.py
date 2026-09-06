"""Add auditable payment reversals.

Revision ID: 0008_payment_reversals
Revises: 0007_receipts_email_outbox
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_payment_reversals"
down_revision = "0007_receipts_email_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'REVERSED'")
    op.execute("ALTER TYPE contribution_status ADD VALUE IF NOT EXISTS 'REVERSED'")
    op.drop_constraint("ck_receipts_status", "receipts", type_="check")
    op.create_check_constraint(
        "ck_receipts_status",
        "receipts",
        "status IN ('PENDING_GENERATION', 'GENERATED', 'FAILED', 'VOID')",
    )
    op.create_table(
        "payment_reversals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_fund_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reversal_fund_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reversed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["original_fund_entry_id"], ["fund_entries.id"]),
        sa.ForeignKeyConstraint(["reversal_fund_entry_id"], ["fund_entries.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.UniqueConstraint("payment_id", name="uq_payment_reversals_payment_id"),
        sa.UniqueConstraint(
            "original_fund_entry_id", name="uq_payment_reversals_original_entry"
        ),
        sa.UniqueConstraint(
            "reversal_fund_entry_id", name="uq_payment_reversals_reversal_entry"
        ),
    )
    op.create_index(
        "ix_payment_reversals_payment_id", "payment_reversals", ["payment_id"]
    )
    op.execute('ALTER TABLE public."payment_reversals" ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public."payment_reversals" FROM anon, authenticated')


def downgrade() -> None:
    op.drop_index("ix_payment_reversals_payment_id", table_name="payment_reversals")
    op.drop_table("payment_reversals")
    op.drop_constraint("ck_receipts_status", "receipts", type_="check")
    op.create_check_constraint(
        "ck_receipts_status",
        "receipts",
        "status IN ('PENDING_GENERATION', 'GENERATED', 'FAILED')",
    )
    # PostgreSQL enum values are intentionally retained on downgrade.

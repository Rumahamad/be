"""Complete expense fields and immutable reversal records.

Revision ID: 0010_expense_lifecycle
Revises: 0009_organization_controls
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_expense_lifecycle"
down_revision = "0009_organization_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS payee VARCHAR(200)")
    op.execute(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS responsible_member_id UUID "
        "REFERENCES users(id)"
    )
    op.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50)")
    op.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS reference_no VARCHAR(120)")
    op.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS internal_note TEXT")
    op.execute(
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS status VARCHAR(20) "
        "NOT NULL DEFAULT 'POSTED'"
    )
    op.create_check_constraint(
        "ck_expenses_status", "expenses", "status IN ('POSTED', 'REVERSED')"
    )
    op.create_index(
        "ix_expenses_responsible_member_id", "expenses", ["responsible_member_id"]
    )
    op.create_table(
        "expense_reversals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("expense_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_fund_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reversal_fund_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reversed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"]),
        sa.ForeignKeyConstraint(["original_fund_entry_id"], ["fund_entries.id"]),
        sa.ForeignKeyConstraint(["reversal_fund_entry_id"], ["fund_entries.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.UniqueConstraint("expense_id", name="uq_expense_reversals_expense_id"),
        sa.UniqueConstraint(
            "original_fund_entry_id", name="uq_expense_reversals_original_entry"
        ),
        sa.UniqueConstraint(
            "reversal_fund_entry_id", name="uq_expense_reversals_reversal_entry"
        ),
    )
    op.create_index(
        "ix_expense_reversals_expense_id", "expense_reversals", ["expense_id"]
    )
    op.execute('ALTER TABLE public."expense_reversals" ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public."expense_reversals" FROM anon, authenticated')


def downgrade() -> None:
    op.drop_index("ix_expense_reversals_expense_id", table_name="expense_reversals")
    op.drop_table("expense_reversals")
    op.drop_index("ix_expenses_responsible_member_id", table_name="expenses")
    op.drop_constraint("ck_expenses_status", "expenses", type_="check")
    for column in (
        "status",
        "internal_note",
        "reference_no",
        "payment_method",
        "responsible_member_id",
        "payee",
    ):
        op.drop_column("expenses", column)

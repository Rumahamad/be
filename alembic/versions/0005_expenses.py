"""Add immutable fund expenses.

Revision ID: 0005_expenses
Revises: 0004_active_contribution_unique_index
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_expenses"
down_revision = "0004_active_contribution_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("fund_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fund_account_id"], ["fund_accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_expenses_fund_account_id", "expenses", ["fund_account_id"])
    op.execute('ALTER TABLE public."expenses" ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public."expenses" FROM anon, authenticated')


def downgrade() -> None:
    op.drop_index("ix_expenses_fund_account_id", table_name="expenses")
    op.drop_table("expenses")

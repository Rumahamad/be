"""Add expense category hierarchy and private attachment links.

Revision ID: 0013_expense_categories_attachments
Revises: 0012_contribution_reminders
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013_expense_categories_attachments"
down_revision = "0012_contribution_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["expense_categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.CheckConstraint("id <> parent_id", name="ck_expense_category_not_self"),
        sa.UniqueConstraint("code", name="uq_expense_categories_code"),
    )
    op.create_index("ix_expense_categories_parent_id", "expense_categories", ["parent_id"])
    op.add_column(
        "expenses",
        sa.Column("expense_category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_expenses_expense_category_id",
        "expenses",
        "expense_categories",
        ["expense_category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_expenses_expense_category_id", "expenses", ["expense_category_id"])
    op.create_table(
        "expense_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("expense_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.UniqueConstraint("file_id", name="uq_expense_attachments_file_id"),
        sa.UniqueConstraint("expense_id", "file_id", name="uq_expense_attachment_file"),
    )
    op.create_index("ix_expense_attachments_expense_id", "expense_attachments", ["expense_id"])
    for table in ("expense_categories", "expense_attachments"):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')


def downgrade() -> None:
    op.drop_index("ix_expense_attachments_expense_id", table_name="expense_attachments")
    op.drop_table("expense_attachments")
    op.drop_index("ix_expenses_expense_category_id", table_name="expenses")
    op.drop_constraint("fk_expenses_expense_category_id", "expenses", type_="foreignkey")
    op.drop_column("expenses", "expense_category_id")
    op.drop_index("ix_expense_categories_parent_id", table_name="expense_categories")
    op.drop_table("expense_categories")

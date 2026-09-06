"""Add idempotent contribution reminder delivery records.

Revision ID: 0012_contribution_reminders
Revises: 0011_outbox_cancellation
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_contribution_reminders"
down_revision = "0011_outbox_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contribution_reminder_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("days_before", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_reminder_month"),
        sa.CheckConstraint("days_before >= 0", name="ck_reminder_days_before"),
        sa.UniqueConstraint(
            "user_id",
            "year",
            "month",
            "days_before",
            name="uq_contribution_reminder_delivery",
        ),
    )
    op.create_index(
        "ix_contribution_reminder_user_id",
        "contribution_reminder_deliveries",
        ["user_id"],
    )
    op.execute(
        'ALTER TABLE public."contribution_reminder_deliveries" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        'REVOKE ALL ON TABLE public."contribution_reminder_deliveries" FROM anon, authenticated'
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contribution_reminder_user_id",
        table_name="contribution_reminder_deliveries",
    )
    op.drop_table("contribution_reminder_deliveries")

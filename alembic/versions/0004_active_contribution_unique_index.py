"""Allow rejected contribution months to be submitted again.

Revision ID: 0004_active_contribution_unique_index
Revises: 0003_password_setup_required
Create Date: 2026-09-02
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_active_contribution_unique_index"
down_revision = "0003_password_setup_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A rejected submission is not a contribution. Keep it for audit/history,
    # but do not let its unique key block a corrected submission.
    op.drop_constraint(
        "uq_member_contribution_month",
        "member_month_contributions",
        type_="unique",
    )
    op.create_index(
        "uq_member_contribution_month_active",
        "member_month_contributions",
        ["member_id", "year", "month"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'APPROVED')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_member_contribution_month_active",
        table_name="member_month_contributions",
    )
    op.create_unique_constraint(
        "uq_member_contribution_month",
        "member_month_contributions",
        ["member_id", "year", "month"],
    )

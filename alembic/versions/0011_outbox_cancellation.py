"""Allow stale queued notifications to be cancelled.

Revision ID: 0011_outbox_cancellation
Revises: 0010_expense_lifecycle
Create Date: 2026-09-04
"""

from alembic import op

revision = "0011_outbox_cancellation"
down_revision = "0010_expense_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_notification_outbox_status", "notification_outbox", type_="check"
    )
    op.create_check_constraint(
        "ck_notification_outbox_status",
        "notification_outbox",
        "status IN ('PENDING', 'PROCESSING', 'SENT', 'FAILED', 'CANCELLED')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE notification_outbox SET status = 'FAILED' WHERE status = 'CANCELLED'"
    )
    op.drop_constraint(
        "ck_notification_outbox_status", "notification_outbox", type_="check"
    )
    op.create_check_constraint(
        "ck_notification_outbox_status",
        "notification_outbox",
        "status IN ('PENDING', 'PROCESSING', 'SENT', 'FAILED')",
    )

"""Expand notification_outbox channel constraint to include PUSH.

Revision ID: 0015_push_channel
Revises: 0014_push_subscriptions
Create Date: 2026-09-04
"""

from alembic import op

revision = "0015_push_channel"
down_revision = "0014_push_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_notification_outbox_channel", "notification_outbox", type_="check"
    )
    op.create_check_constraint(
        "ck_notification_outbox_channel",
        "notification_outbox",
        "channel IN ('EMAIL', 'PUSH')",
    )


def downgrade() -> None:
    # Remove any PUSH rows before reverting
    op.execute("DELETE FROM notification_outbox WHERE channel = 'PUSH'")
    op.drop_constraint(
        "ck_notification_outbox_channel", "notification_outbox", type_="check"
    )
    op.create_check_constraint(
        "ck_notification_outbox_channel",
        "notification_outbox",
        "channel IN ('EMAIL')",
    )

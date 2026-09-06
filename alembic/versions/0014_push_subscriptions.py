"""Add push_subscriptions table and PUSH channel support

Revision ID: 0014_push_subscriptions
Revises: 0013_expense_categories_attachments
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_push_subscriptions"
down_revision = "0013_expense_categories_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("p256dh", sa.String(256), nullable=False),
        sa.Column("auth", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "endpoint", name="uq_push_subscription_user_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_index("ix_push_subscriptions_is_active", "push_subscriptions", ["is_active"])


def downgrade() -> None:
    op.drop_table("push_subscriptions")

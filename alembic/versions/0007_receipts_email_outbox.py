"""Add payment receipts and reliable email outbox.

Revision ID: 0007_receipts_email_outbox
Revises: 0006_announcements_notifications
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_receipts_email_outbox"
down_revision = "0006_announcements_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("receipt_no", sa.String(40), nullable=False, unique=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING_GENERATION', 'GENERATED', 'FAILED')",
            name="ck_receipts_status",
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
    )
    op.create_index("ix_receipts_payment_id", "receipts", ["payment_id"], unique=True)
    op.create_table(
        "notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("template_key", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("channel IN ('EMAIL')", name="ck_notification_outbox_channel"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SENT', 'FAILED')",
            name="ck_notification_outbox_status",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_notification_outbox_event_type", "notification_outbox", ["event_type"])
    op.create_index(
        "ix_notification_outbox_recipient_user_id",
        "notification_outbox",
        ["recipient_user_id"],
    )
    op.create_index("ix_notification_outbox_status", "notification_outbox", ["status"])
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["status", "next_retry_at", "created_at"],
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('SENT', 'FAILED')", name="ck_notification_deliveries_status"
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id"], ["notification_outbox.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "outbox_id", "attempt_no", name="uq_notification_delivery_attempt"
        ),
    )
    op.create_index(
        "ix_notification_deliveries_outbox_id",
        "notification_deliveries",
        ["outbox_id"],
    )

    for table in ("receipts", "notification_outbox", "notification_deliveries"):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_outbox_id", table_name="notification_deliveries"
    )
    op.drop_table("notification_deliveries")
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_status", table_name="notification_outbox")
    op.drop_index(
        "ix_notification_outbox_recipient_user_id", table_name="notification_outbox"
    )
    op.drop_index("ix_notification_outbox_event_type", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("ix_receipts_payment_id", table_name="receipts")
    op.drop_table("receipts")

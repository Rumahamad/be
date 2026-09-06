"""Add targeted announcements and in-app notifications.

Revision ID: 0006_announcements_notifications
Revises: 0005_expenses
Create Date: 2026-09-03
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_announcements_notifications"
down_revision = "0005_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "priority IN ('NORMAL', 'IMPORTANT', 'CRITICAL')",
            name="ck_announcements_priority",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'SCHEDULED', 'PUBLISHED', 'EXPIRED')",
            name="ck_announcements_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index(
        "ix_announcements_visibility",
        "announcements",
        ["status", "publish_at", "expire_at"],
    )
    op.create_table(
        "announcement_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("announcement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "(target_type = 'ALL' AND target_id IS NULL) OR "
            "(target_type IN ('ROLE', 'GROUP', 'USER') AND target_id IS NOT NULL)",
            name="ck_announcement_targets_shape",
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"], ["announcements.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "announcement_id", "target_type", "target_id", name="uq_announcement_target"
        ),
    )
    op.create_index(
        "ix_announcement_targets_announcement_id",
        "announcement_targets",
        ["announcement_id"],
    )
    op.create_index(
        "ix_announcement_targets_audience",
        "announcement_targets",
        ["target_type", "target_id", "announcement_id"],
    )
    op.create_table(
        "announcement_reads",
        sa.Column("announcement_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["announcement_id"], ["announcements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reference_type", sa.String(60), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "is_read", "created_at"],
    )

    for table in (
        "announcements",
        "announcement_targets",
        "announcement_reads",
        "notifications",
    ):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')

    permission_id = uuid.uuid4()
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, module, action, scope, description) "
            "VALUES (:id, 'announcement.manage.all', 'announcement', 'manage', 'all', NULL) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"id": permission_id},
    )
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id, allowed) "
            "SELECT roles.id, permissions.id, TRUE FROM roles CROSS JOIN permissions "
            "WHERE roles.code = 'ADMIN' AND permissions.code = 'announcement.manage.all' "
            "ON CONFLICT (role_id, permission_id) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code = 'announcement.manage.all')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'announcement.manage.all'")
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("announcement_reads")
    op.drop_index("ix_announcement_targets_audience", table_name="announcement_targets")
    op.drop_index(
        "ix_announcement_targets_announcement_id", table_name="announcement_targets"
    )
    op.drop_table("announcement_targets")
    op.drop_index("ix_announcements_visibility", table_name="announcements")
    op.drop_table("announcements")

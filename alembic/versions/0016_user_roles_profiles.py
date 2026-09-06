"""Add user deletion, profile pictures, and dynamic role support.

Revision ID: 0016_user_roles_profiles
Revises: 0015_push_channel
Create Date: 2026-09-04
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016_user_roles_profiles"
down_revision = "0015_push_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'DELETED'")
    op.add_column(
        "users",
        sa.Column("profile_picture_file_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_profile_picture_file_id",
        "users",
        "files",
        ["profile_picture_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "deleted_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("original_user_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("member_code", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )

    connection = op.get_bind()
    permission_id = uuid.uuid4()
    connection.execute(
        sa.text(
            """
            INSERT INTO permissions (id, code, module, action, scope, description)
            VALUES (:id, 'user.delete', 'user', 'delete', 'all',
                    'Archive and anonymize a user account')
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {"id": permission_id},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id, allowed)
            SELECT roles.id, permissions.id, true
            FROM roles CROSS JOIN permissions
            WHERE roles.code = 'ADMIN' AND permissions.code = 'user.delete'
            ON CONFLICT (role_id, permission_id) DO UPDATE SET allowed = true
            """
        )
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code = 'user.delete')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'user.delete'")
    op.drop_table("deleted_users")
    op.drop_constraint("fk_users_profile_picture_file_id", "users", type_="foreignkey")
    op.drop_column("users", "profile_picture_file_id")
    # PostgreSQL enum values are intentionally retained on downgrade.

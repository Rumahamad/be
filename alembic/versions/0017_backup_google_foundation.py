"""Add backup metadata and owner Google OAuth storage.

Revision ID: 0017_backup_google_foundation
Revises: 0016_user_roles_profiles
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017_backup_google_foundation"
down_revision = "0016_user_roles_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("account_subject", sa.String(255), nullable=False),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("granted_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("connected_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("root_folder_id", sa.String(255)),
        sa.Column("root_web_link", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connected_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("purpose", name="uq_google_connection_purpose"),
        sa.CheckConstraint("status IN ('ACTIVE', 'ERROR', 'REVOKED')", name="ck_google_connection_status"),
    )
    op.create_index("ix_google_connections_connected_by", "google_connections", ["connected_by"])
    op.create_table(
        "google_oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_code_verifier", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_google_oauth_states_created_by", "google_oauth_states", ["created_by"])
    op.create_index("ix_google_oauth_state_expiry", "google_oauth_states", ["expires_at"])
    op.create_table(
        "backup_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_type", sa.String(20), nullable=False),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("source_cutoff", sa.DateTime(timezone=True)),
        sa.Column("drive_folder_id", sa.String(255)),
        sa.Column("manifest_file_id", sa.String(255)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("run_type IN ('DAILY', 'WEEKLY', 'MONTHLY', 'MANUAL')", name="ck_backup_run_type"),
        sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')", name="ck_backup_run_status"),
    )
    op.create_index("ix_backup_runs_status_created", "backup_runs", ["status", "created_at"])
    op.create_index("ix_backup_runs_requested_by", "backup_runs", ["requested_by"])
    op.execute(
        "CREATE UNIQUE INDEX uq_backup_runs_one_active ON backup_runs ((1)) "
        "WHERE status IN ('PENDING', 'RUNNING')"
    )
    op.create_table(
        "backup_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_key", sa.String(180), nullable=False, unique=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('PENDING', 'PROCESSING', 'DONE', 'FAILED')", name="ck_backup_outbox_status"),
    )
    op.create_index("ix_backup_outbox_due", "backup_outbox", ["status", "next_retry_at", "created_at"])


def downgrade() -> None:
    op.drop_table("backup_outbox")
    op.drop_table("backup_runs")
    op.drop_table("google_oauth_states")
    op.drop_table("google_connections")

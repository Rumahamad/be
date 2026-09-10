"""Repair backup schema added after revision 0017 was first applied.

Revision ID: 0018_backup_schema_repair
Revises: 0017_backup_google_foundation
"""

from alembic import op


revision = "0018_backup_schema_repair"
down_revision = "0017_backup_google_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0017 was applied before these fields were added to its source.
    # IF NOT EXISTS keeps this forward repair safe for databases created later
    # from the final 0017 definition.
    op.execute(
        "ALTER TABLE google_connections "
        "ADD COLUMN IF NOT EXISTS root_folder_id VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE google_connections "
        "ADD COLUMN IF NOT EXISTS root_web_link VARCHAR(1000)"
    )
    op.execute(
        "ALTER TABLE backup_runs "
        "ADD COLUMN IF NOT EXISTS requested_by UUID"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_backup_runs_requested_by_users'
                  AND conrelid = 'backup_runs'::regclass
            ) THEN
                ALTER TABLE backup_runs
                    ADD CONSTRAINT fk_backup_runs_requested_by_users
                    FOREIGN KEY (requested_by) REFERENCES users(id)
                    ON DELETE SET NULL;
            END IF;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backup_runs_requested_by "
        "ON backup_runs (requested_by)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_backup_runs_one_active "
        "ON backup_runs ((1)) WHERE status IN ('PENDING', 'RUNNING')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_backup_runs_one_active")
    op.execute("DROP INDEX IF EXISTS ix_backup_runs_requested_by")
    op.execute(
        "ALTER TABLE backup_runs "
        "DROP CONSTRAINT IF EXISTS fk_backup_runs_requested_by_users"
    )
    op.execute("ALTER TABLE backup_runs DROP COLUMN IF EXISTS requested_by")
    op.execute("ALTER TABLE google_connections DROP COLUMN IF EXISTS root_web_link")
    op.execute("ALTER TABLE google_connections DROP COLUMN IF EXISTS root_folder_id")

"""Track invited users who must choose their first password.

Revision ID: 0003_password_setup_required
Revises: 0002_member_code_sequence
Create Date: 2026-09-02
"""

from alembic import op

revision = "0003_password_setup_required"
down_revision = "0002_member_code_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Later descriptive revision IDs exceed Alembic's historical VARCHAR(32)
    # default. Widen it before Alembic records the next revision.
    op.execute(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
    )
    # The initial migration builds metadata from the installed application model.
    # IF NOT EXISTS keeps both fresh databases and older 0002 databases valid.
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "password_setup_required BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE users ALTER COLUMN password_setup_required DROP DEFAULT")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_setup_required")

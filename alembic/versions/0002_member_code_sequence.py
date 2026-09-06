"""Add concurrency-safe member code sequence.

Revision ID: 0002_member_code_sequence
Revises: 0001_initial_core
Create Date: 2026-09-02
"""

from alembic import op

revision = "0002_member_code_sequence"
down_revision = "0001_initial_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE bnc_member_code_seq START WITH 2")


def downgrade() -> None:
    op.execute("DROP SEQUENCE bnc_member_code_seq")

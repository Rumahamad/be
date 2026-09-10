"""Finalize safe payment verification reference ownership.

Revision ID: 0020_payment_verification_safety
Revises: 0019_payment_verification
"""

import sqlalchemy as sa

from alembic import op


revision = "0020_payment_verification_safety"
down_revision = "0019_payment_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only authenticated READY credits may reserve an external UPI reference.
    op.add_column(
        "incoming_upi_credits",
        sa.Column("observed_upi_reference", sa.String(40)),
    )
    op.execute(sa.text(
        "UPDATE incoming_upi_credits "
        "SET observed_upi_reference = upi_reference, upi_reference = NULL "
        "WHERE parse_status <> 'READY'"
    ))
    op.execute(sa.text(
        "UPDATE incoming_upi_credits SET observed_upi_reference = upi_reference "
        "WHERE parse_status = 'READY'"
    ))
    op.create_index(
        "ix_incoming_upi_credit_ready_unconsumed",
        "incoming_upi_credits",
        ["upi_reference"],
        unique=False,
        postgresql_where=sa.text("parse_status = 'READY' AND consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_incoming_upi_credit_ready_unconsumed",
        table_name="incoming_upi_credits",
    )
    op.drop_column("incoming_upi_credits", "observed_upi_reference")

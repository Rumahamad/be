"""Add organization visibility and reminder controls.

Revision ID: 0009_organization_controls
Revises: 0008_payment_reversals
Create Date: 2026-09-03
"""

from alembic import op

revision = "0009_organization_controls"
down_revision = "0008_payment_reversals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organization_settings ADD COLUMN IF NOT EXISTS "
        "expense_visibility VARCHAR(20) NOT NULL DEFAULT 'SUMMARY'"
    )
    op.execute(
        "ALTER TABLE organization_settings ADD COLUMN IF NOT EXISTS "
        "expense_visible_fields JSONB NOT NULL "
        "DEFAULT '[\"category\", \"amount\", \"expense_date\"]'::jsonb"
    )
    op.execute(
        "ALTER TABLE organization_settings ADD COLUMN IF NOT EXISTS "
        "reminder_days_before_month_end JSONB NOT NULL DEFAULT '[5, 1]'::jsonb"
    )
    op.create_check_constraint(
        "ck_organization_settings_expense_visibility",
        "organization_settings",
        "expense_visibility IN ('HIDDEN', 'SUMMARY', 'DETAILS')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_organization_settings_expense_visibility",
        "organization_settings",
        type_="check",
    )
    op.drop_column("organization_settings", "reminder_days_before_month_end")
    op.drop_column("organization_settings", "expense_visible_fields")
    op.drop_column("organization_settings", "expense_visibility")

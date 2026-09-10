"""Persist authentication evidence and permanent UTR ownership."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0021_arc_evidence'
down_revision = '0020_payment_verification_safety'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('incoming_upi_credits', sa.Column('authentication_evidence', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_table('payment_utr_claims',
        sa.Column('reference', sa.String(40), primary_key=True),
        sa.Column('payment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payments.id'), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_payment_utr_claims_payment_id', 'payment_utr_claims', ['payment_id'])
    # Preserve known historical usage. Ambiguous historical claims are still
    # blocked by the reconciliation query across approved/reversed payments.
    op.execute("""INSERT INTO payment_utr_claims(reference, payment_id)
        SELECT reference, payment_id FROM (
          SELECT DISTINCT ON(reference) reference, payment_id FROM (
            SELECT auto_verified_reference AS reference, id AS payment_id FROM payments
              WHERE status IN ('APPROVED','REVERSED') AND auto_verified_reference IS NOT NULL
            UNION SELECT e.selected_upi_reference, e.payment_id FROM payment_proof_extractions e
              JOIN payments p ON p.id=e.payment_id
              WHERE p.status IN ('APPROVED','REVERSED') AND e.selected_upi_reference IS NOT NULL
          ) candidates ORDER BY reference, payment_id
        ) claims ON CONFLICT DO NOTHING""")


def downgrade():
    op.drop_table('payment_utr_claims')
    op.drop_column('incoming_upi_credits', 'authentication_evidence')

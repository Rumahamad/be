"""Keep backend-only tables inaccessible through public Supabase API roles."""

from alembic import op
from sqlalchemy import inspect, text

revision = "0023_backend_tables_rls"
down_revision = "0022_local_auth"
branch_labels = None
depends_on = None

BACKEND_TABLES = (
    "alembic_version", "google_connections", "google_oauth_states", "backup_runs",
    "push_subscriptions", "deleted_users", "backup_outbox", "payment_proof_extractions",
    "payment_verification_events", "incoming_upi_credits", "payment_utr_claims",
    "local_auth_identities", "local_auth_sessions", "local_auth_tokens",
)


def upgrade():
    bind = op.get_bind()
    available = set(inspect(bind).get_table_names(schema="public"))
    for table in BACKEND_TABLES:
        if table in available:
            # No public API policies: only the trusted backend connection and
            # Supabase service role may access these records.
            bind.execute(text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))


def downgrade():
    # Preserve protection when rolling back application versions.
    pass

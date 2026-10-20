"""Add local authentication without modifying existing identities or business data."""
from alembic import op
from app.models.local_auth import LocalIdentity, LocalSession, LocalToken

revision = "0022_local_auth"
down_revision = "0021_arc_evidence"
branch_labels = None
depends_on = None


def upgrade():
    for model in (LocalIdentity, LocalSession, LocalToken):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in (LocalToken, LocalSession, LocalIdentity):
        model.__table__.drop(op.get_bind(), checkfirst=True)

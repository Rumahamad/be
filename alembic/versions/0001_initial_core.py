"""Create the initial BNC application schema.

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-09-02
"""

import uuid

from alembic import op
from app.constants.permissions import PERMISSION_DEFINITIONS, ROLE_PERMISSION_CODES
from app.db.session import Base
from app.models import core  # noqa: F401
from app.models.fund import FundAccount
from app.models.identity import Permission, Role, RolePermission
from app.models.settings import OrganizationSetting

revision = "0001_initial_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    Base.metadata.create_all(bind)

    role_ids = {code: uuid.uuid4() for code in ROLE_PERMISSION_CODES}
    bind.execute(Role.__table__.insert(), [
        {"id": role_id, "code": code, "name": code.title(), "description": f"System {code.lower()} role",
         "is_system": True, "is_protected": True, "is_active": True}
        for code, role_id in role_ids.items()
    ])

    permission_ids = {code: uuid.uuid4() for code in PERMISSION_DEFINITIONS}
    bind.execute(Permission.__table__.insert(), [
        {"id": permission_ids[code], "code": code, "module": parts[0], "action": parts[1],
         "scope": ".".join(parts[2:]), "description": None}
        for code, parts in PERMISSION_DEFINITIONS.items()
    ])
    bind.execute(RolePermission.__table__.insert(), [
        {"role_id": role_ids[role], "permission_id": permission_ids[code], "allowed": True}
        for role, codes in ROLE_PERMISSION_CODES.items() for code in codes
    ])
    bind.execute(FundAccount.__table__.insert(), [{
        "id": uuid.uuid4(), "name": "BNC General Fund", "code": "GENERAL",
        "account_type": "GENERAL", "is_default": True, "is_active": True,
    }])
    bind.execute(OrganizationSetting.__table__.insert(), [{
        "id": uuid.uuid4(),
        "organization_name": "Bamarrrah Naujawan Committee",
        "short_name": "BNC",
        "payment_upi_id": "kayef.ahamad@ybl",
        "payment_mobile": "9800189919",
        "payment_qr_path": "/api/v1/settings/payment/qr",
        "whatsapp_group_url": "https://chat.whatsapp.com/JJFMRoNlE7zIiCVRiWe9HP",
        "default_language": "en",
        "default_theme": "bnc-green",
    }])

    # The frontend never talks directly to financial tables. Keep Supabase Data API closed;
    # FastAPI accesses these tables through the database connection.
    for table in Base.metadata.sorted_tables:
        op.execute(f'ALTER TABLE public."{table.name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table.name}" FROM anon, authenticated')


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())

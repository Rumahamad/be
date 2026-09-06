from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditOutput(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID | None
    before_data: dict | None
    after_data: dict | None
    created_at: datetime


class AuditListOutput(BaseModel):
    items: list[AuditOutput]
    total: int

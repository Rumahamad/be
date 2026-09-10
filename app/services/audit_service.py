from uuid import uuid4
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.backup import BackupOutbox


class AuditService:
    def record(
        self,
        db: Session,
        *,
        actor_user_id: UUID,
        action: str,
        entity_type: str,
        entity_id: UUID,
        before_data: dict | None = None,
        after_data: dict | None = None,
    ) -> None:
        db.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_data=before_data,
                after_data=after_data,
            )
        )
        if not action.startswith("backup."):
            event_id = uuid4()
            db.add(BackupOutbox(
                id=event_id,
                event_key=f"audit:{event_id}",
                event_type=action[:80],
                entity_type=entity_type[:80],
                entity_id=entity_id,
                payload={"action": action},
            ))

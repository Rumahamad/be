from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


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

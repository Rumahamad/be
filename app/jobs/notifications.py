from app.db.session import SessionLocal
from app.services.outbox_service import OutboxService


def process_notification_outbox(limit: int = 50) -> int:
    with SessionLocal.begin() as db:
        return OutboxService().process_due(db, limit=limit)

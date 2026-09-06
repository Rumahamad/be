from app.db.session import SessionLocal
from app.services.push_outbox_service import PushOutboxService


def process_push_outbox(limit: int = 100) -> int:
    with SessionLocal.begin() as db:
        return PushOutboxService().process_due(db, limit=limit)

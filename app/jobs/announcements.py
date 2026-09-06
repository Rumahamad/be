from app.db.session import SessionLocal
from app.services.announcement_service import AnnouncementService


def process_due_announcements(limit: int = 100) -> int:
    with SessionLocal.begin() as db:
        return AnnouncementService().publish_due(db, limit=limit)

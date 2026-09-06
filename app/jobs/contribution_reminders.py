from app.db.session import SessionLocal
from app.services.contribution_reminder_service import ContributionReminderService


def process_contribution_reminders() -> int:
    with SessionLocal.begin() as db:
        return ContributionReminderService().process_due(db)

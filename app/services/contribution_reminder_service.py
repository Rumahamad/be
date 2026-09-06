import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.communications import ContributionReminderDelivery
from app.models.enums import ContributionStatus, UserStatus
from app.models.identity import User
from app.models.payments import MemberMonthContribution
from app.services.announcement_service import NotificationService
from app.services.settings_service import SettingsService

INDIA_TIME_ZONE = ZoneInfo("Asia/Kolkata")


class ContributionReminderService:
    def process_due(self, db: Session, *, today: date | None = None) -> int:
        reminder_date = today or datetime.now(INDIA_TIME_ZONE).date()
        month_end = date(
            reminder_date.year,
            reminder_date.month,
            calendar.monthrange(reminder_date.year, reminder_date.month)[1],
        )
        days_before = (month_end - reminder_date).days
        configured_days = SettingsService.get_model(db).reminder_days_before_month_end
        if days_before not in configured_days:
            return 0

        covered = exists(
            select(MemberMonthContribution.id).where(
                MemberMonthContribution.member_id == User.id,
                MemberMonthContribution.year == reminder_date.year,
                MemberMonthContribution.month == reminder_date.month,
                MemberMonthContribution.status.in_(
                    (ContributionStatus.PENDING, ContributionStatus.APPROVED)
                ),
            )
        )
        user_ids = db.scalars(
            select(User.id).where(User.status == UserStatus.ACTIVE, ~covered)
        ).all()

        notification_service = NotificationService()
        created = 0
        month_label = calendar.month_name[reminder_date.month]
        for user_id in user_ids:
            reminder_id = db.scalar(
                insert(ContributionReminderDelivery)
                .values(
                    user_id=user_id,
                    year=reminder_date.year,
                    month=reminder_date.month,
                    days_before=days_before,
                )
                .on_conflict_do_nothing(
                    constraint="uq_contribution_reminder_delivery"
                )
                .returning(ContributionReminderDelivery.id)
            )
            if reminder_id is None:
                continue
            notification_service.create_for_users(
                db,
                user_ids=[user_id],
                event_type="CONTRIBUTION_REMINDER",
                title=f"{month_label} contribution reminder",
                message=(
                    f"Your {month_label} {reminder_date.year} contribution is still due. "
                    f"The month ends in {days_before} day{'s' if days_before != 1 else ''}."
                ),
                reference_type="contribution_month",
                email_payload={
                    "year": reminder_date.year,
                    "month": reminder_date.month,
                    "days_before": days_before,
                },
            )
            created += 1
        return created

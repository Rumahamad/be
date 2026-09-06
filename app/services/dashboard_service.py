from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ContributionStatus
from app.models.identity import User
from app.models.payments import MemberMonthContribution
from app.schemas.dashboard import CurrentMonthOutput, DashboardOutput, RecentContributionOutput


class DashboardService:
    def get_member_dashboard(self, db: Session, user: User) -> DashboardOutput:
        today = datetime.now(UTC).date()
        approved = ContributionStatus.APPROVED
        current = db.scalar(
            select(MemberMonthContribution)
            .where(
                MemberMonthContribution.member_id == user.id,
                MemberMonthContribution.year == today.year,
                MemberMonthContribution.month == today.month,
                MemberMonthContribution.status.in_(
                    (ContributionStatus.PENDING, ContributionStatus.APPROVED)
                ),
            )
            .order_by(MemberMonthContribution.created_at.desc())
            .limit(1)
        )
        current_year_total = db.scalar(
            select(func.coalesce(func.sum(MemberMonthContribution.amount), 0)).where(
                MemberMonthContribution.member_id == user.id,
                MemberMonthContribution.year == today.year,
                MemberMonthContribution.status == approved,
            )
        )
        lifetime_total = db.scalar(
            select(func.coalesce(func.sum(MemberMonthContribution.amount), 0)).where(
                MemberMonthContribution.member_id == user.id,
                MemberMonthContribution.status == approved,
            )
        )
        month_count = db.scalar(
            select(func.count(MemberMonthContribution.id)).where(
                MemberMonthContribution.member_id == user.id,
                MemberMonthContribution.year == today.year,
                MemberMonthContribution.status == approved,
            )
        )
        recent = db.scalars(
            select(MemberMonthContribution)
            .where(
                MemberMonthContribution.member_id == user.id,
            )
            .order_by(MemberMonthContribution.year.desc(), MemberMonthContribution.month.desc())
            .limit(5)
        ).all()
        return DashboardOutput(
            display_name=user.display_name,
            current_month=CurrentMonthOutput(
                year=today.year,
                month=today.month,
                status=current.status.value if current else "AVAILABLE",
                amount=current.amount if current else None,
                payment_id=str(current.payment_id) if current else None,
            ),
            current_year_total=Decimal(current_year_total or 0),
            lifetime_total=Decimal(lifetime_total or 0),
            contributed_months_current_year=int(month_count or 0),
            elapsed_months_current_year=today.month,
            recent_contributions=[
                RecentContributionOutput(
                    year=item.year,
                    month=item.month,
                    amount=item.amount,
                    status=item.status.value,
                )
                for item in recent
            ],
        )

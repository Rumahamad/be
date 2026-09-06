from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.db.session import get_db
from app.models.identity import User
from app.schemas.dashboard import DashboardOutput
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/me", tags=["member"])
service = DashboardService()


@router.get("/dashboard", response_model=DashboardOutput)
def member_dashboard(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> DashboardOutput:
    return service.get_member_dashboard(db, user)

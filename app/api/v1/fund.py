from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.constants.permissions import FUND_ADJUST, FUND_VIEW
from app.db.session import get_db
from app.models.identity import User
from app.schemas.fund import (
    CreateFundAdjustmentInput,
    FundEntryListOutput,
    FundEntryOutput,
    FundSummaryOutput,
    ReverseFundEntryInput,
)
from app.services.fund_service import FundService

router = APIRouter(prefix="/fund", tags=["fund"])
service = FundService()


@router.get("/summary", response_model=FundSummaryOutput)
def fund_summary(
    db: Session = Depends(get_db), _: User = Depends(require_permission(FUND_VIEW))
) -> FundSummaryOutput:
    return service.summary(db)


@router.get("/entries", response_model=FundEntryListOutput)
def fund_entries(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(FUND_VIEW)),
) -> FundEntryListOutput:
    return service.entries(db, offset=offset, limit=limit)


@router.post("/entries", response_model=FundEntryOutput)
def create_fund_adjustment(
    payload: CreateFundAdjustmentInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(FUND_ADJUST)),
) -> FundEntryOutput:
    entry = service.create_adjustment(db, actor, payload)
    db.commit()
    return service.output(entry)


@router.post("/entries/{entry_id}/reverse", response_model=FundEntryOutput)
def reverse_fund_adjustment(
    entry_id: UUID,
    payload: ReverseFundEntryInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(FUND_ADJUST)),
) -> FundEntryOutput:
    entry = service.reverse_adjustment(db, actor, entry_id, payload.reason)
    db.commit()
    return service.output(entry)

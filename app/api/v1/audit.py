from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.constants.permissions import AUDIT_VIEW
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.identity import User
from app.schemas.audit import AuditListOutput, AuditOutput

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListOutput)
def list_audit(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(AUDIT_VIEW)),
) -> AuditListOutput:
    total = db.scalar(select(func.count(AuditLog.id))) or 0
    rows = db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return AuditListOutput(
        items=[
            AuditOutput(
                id=item.id,
                actor_user_id=item.actor_user_id,
                action=item.action,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                before_data=item.before_data,
                after_data=item.after_data,
                created_at=item.created_at,
            )
            for item in rows
        ],
        total=int(total),
    )

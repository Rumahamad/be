from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_permission, user_has_permission
from app.constants.permissions import (
    EXPENSE_CREATE,
    EXPENSE_VIEW_DETAILS,
    EXPENSE_VIEW_SUMMARY,
    FUND_ADJUST,
    SETTINGS_EDIT,
)
from app.db.session import get_db
from app.handlers.expenses import ExpenseHandler
from app.models.fund import FundEntry
from app.models.identity import User
from app.models.settings import OrganizationSetting
from app.schemas.expenses import (
    CreateExpenseCategoryInput,
    CreateExpenseInput,
    ExpenseAttachmentOutput,
    ExpenseCategoryOutput,
    ExpenseListOutput,
    ExpenseOutput,
    ReverseExpenseInput,
    UpdateExpenseCategoryInput,
)
from app.services.expense_service import ExpenseService

router = APIRouter(prefix="/expenses", tags=["expenses"])
service = ExpenseService()
handler = ExpenseHandler()


def output(
    expense,
    entry_no: str,
    responsible_member_name: str | None = None,
    *,
    visible_fields: set[str] | None = None,
) -> ExpenseOutput:
    show_all = visible_fields is None
    show_responsible = show_all or "responsible_member" in visible_fields
    return ExpenseOutput(
        id=expense.id,
        entry_no=entry_no,
        category_id=expense.expense_category_id,
        amount=expense.amount,
        category=expense.category,
        description=expense.description if show_all or "description" in visible_fields else None,
        payee=expense.payee if show_all or "payee" in visible_fields else None,
        responsible_member_id=expense.responsible_member_id if show_responsible else None,
        responsible_member_name=responsible_member_name if show_responsible else None,
        payment_method=(
            expense.payment_method if show_all or "payment_method" in visible_fields else None
        ),
        reference_no=(
            expense.reference_no if show_all or "reference_no" in visible_fields else None
        ),
        internal_note=expense.internal_note if show_all else None,
        status=expense.status,
        expense_date=expense.expense_date,
        created_at=expense.created_at,
    )


@router.get("", response_model=ExpenseListOutput)
def list_expenses(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(EXPENSE_VIEW_SUMMARY)),
) -> ExpenseListOutput:
    can_view_details = user_has_permission(db, user, EXPENSE_VIEW_DETAILS)
    setting = db.scalar(select(OrganizationSetting).limit(1))
    visibility = setting.expense_visibility if setting else "SUMMARY"
    if visibility == "HIDDEN" and not can_view_details:
        raise HTTPException(status_code=403, detail="Expense visibility is disabled")
    visible_fields = None
    if not can_view_details:
        visible_fields = (
            set(setting.expense_visible_fields or [])
            if setting and visibility == "DETAILS"
            else set()
        )
    rows, total = service.list(db, offset=offset, limit=limit)
    return ExpenseListOutput(
        items=[
            output(
                expense,
                entry_no,
                responsible,
                visible_fields=visible_fields,
            )
            for expense, entry_no, responsible in rows
        ],
        total=total,
    )


@router.post("", response_model=ExpenseOutput, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: CreateExpenseInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(EXPENSE_CREATE)),
) -> ExpenseOutput:
    expense = service.create(db, user, payload)
    db.commit()
    db.refresh(expense)
    entry_no = db.scalar(
        select(FundEntry.entry_no).where(
            FundEntry.reference_type == "EXPENSE", FundEntry.reference_id == expense.id
        )
    )
    return output(expense, entry_no or "")


@router.post("/{expense_id}/reverse", response_model=ExpenseOutput)
def reverse_expense(
    expense_id: UUID,
    payload: ReverseExpenseInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(FUND_ADJUST)),
) -> ExpenseOutput:
    expense = service.reverse(db, user, expense_id, payload.reason)
    db.commit()
    original_entry_no = db.scalar(
        select(FundEntry.entry_no).where(
            FundEntry.reference_type == "EXPENSE", FundEntry.reference_id == expense.id
        )
    )
    responsible_name = db.scalar(
        select(User.display_name).where(User.id == expense.responsible_member_id)
    ) if expense.responsible_member_id else None
    return output(expense, original_entry_no or "", responsible_name)


@router.post(
    "/{expense_id}/attachments",
    response_model=ExpenseAttachmentOutput,
    status_code=status.HTTP_201_CREATED,
)
async def upload_expense_attachment(
    expense_id: UUID,
    request: Request,
    filename: str = Query(default="attachment", min_length=1, max_length=255),
    content_type: str = Header(default="application/octet-stream"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(EXPENSE_CREATE)),
) -> ExpenseAttachmentOutput:
    return handler.upload_attachment(
        db,
        user,
        expense_id,
        filename=filename,
        mime_type=content_type,
        content=await request.body(),
    )


@router.get("/{expense_id}/attachments", response_model=list[ExpenseAttachmentOutput])
def list_expense_attachments(
    expense_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ExpenseAttachmentOutput]:
    return handler.list_attachments(db, user, expense_id)


@router.get("/{expense_id}/attachments/{file_id}")
def download_expense_attachment(
    expense_id: UUID,
    file_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    content, media_type, filename = handler.download_attachment(db, user, expense_id, file_id)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/categories", response_model=list[ExpenseCategoryOutput])
def list_expense_categories(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(EXPENSE_VIEW_SUMMARY)),
) -> list[ExpenseCategoryOutput]:
    if include_inactive and not user_has_permission(db, user, SETTINGS_EDIT):
        raise HTTPException(status_code=403, detail="Inactive categories require settings.edit")
    return handler.list_categories(db, include_inactive=include_inactive)


@router.post(
    "/categories", response_model=ExpenseCategoryOutput, status_code=status.HTTP_201_CREATED
)
def create_expense_category(
    payload: CreateExpenseCategoryInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> ExpenseCategoryOutput:
    return handler.create_category(db, actor, payload)


@router.patch("/categories/{category_id}", response_model=ExpenseCategoryOutput)
def update_expense_category(
    category_id: UUID,
    payload: UpdateExpenseCategoryInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> ExpenseCategoryOutput:
    return handler.update_category(db, actor, category_id, payload)

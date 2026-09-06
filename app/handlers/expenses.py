from uuid import UUID

from sqlalchemy.orm import Session

from app.models.identity import User
from app.schemas.expenses import (
    CreateExpenseCategoryInput,
    ExpenseAttachmentOutput,
    ExpenseCategoryOutput,
    UpdateExpenseCategoryInput,
)
from app.services.expense_attachment_service import ExpenseAttachmentService
from app.services.expense_category_service import ExpenseCategoryService


class ExpenseHandler:
    def __init__(self) -> None:
        self.categories = ExpenseCategoryService()
        self.attachments = ExpenseAttachmentService()

    def list_categories(
        self, db: Session, *, include_inactive: bool
    ) -> list[ExpenseCategoryOutput]:
        return self.categories.list(db, include_inactive=include_inactive)

    def create_category(
        self, db: Session, actor: User, payload: CreateExpenseCategoryInput
    ) -> ExpenseCategoryOutput:
        return self.categories.create(db, actor, payload)

    def update_category(
        self,
        db: Session,
        actor: User,
        category_id: UUID,
        payload: UpdateExpenseCategoryInput,
    ) -> ExpenseCategoryOutput:
        return self.categories.update(db, actor, category_id, payload)

    def upload_attachment(
        self,
        db: Session,
        actor: User,
        expense_id: UUID,
        *,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> ExpenseAttachmentOutput:
        return self.attachments.upload(
            db,
            actor,
            expense_id,
            filename=filename,
            mime_type=mime_type,
            content=content,
        )

    def list_attachments(
        self, db: Session, user: User, expense_id: UUID
    ) -> list[ExpenseAttachmentOutput]:
        return self.attachments.list_files(db, user, expense_id)

    def download_attachment(
        self, db: Session, user: User, expense_id: UUID, file_id: UUID
    ) -> tuple[bytes, str, str]:
        return self.attachments.download(db, user, expense_id, file_id)

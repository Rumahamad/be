from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import FileStatus
from app.models.expenses import Expense, ExpenseAttachment, ExpenseCategory
from app.models.files import File as FileRecord


class ExpenseRepository:
    def list_categories(self, db: Session, *, include_inactive: bool) -> list[ExpenseCategory]:
        statement = select(ExpenseCategory)
        if not include_inactive:
            statement = statement.where(ExpenseCategory.is_active.is_(True))
        return list(
            db.scalars(
                statement.order_by(
                    ExpenseCategory.parent_id.nullsfirst(),
                    ExpenseCategory.sort_order,
                    ExpenseCategory.name,
                )
            ).all()
        )

    def get_category(
        self, db: Session, category_id: UUID, *, for_update: bool = False
    ) -> ExpenseCategory | None:
        statement = select(ExpenseCategory).where(ExpenseCategory.id == category_id)
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    def code_exists(self, db: Session, code: str) -> bool:
        return db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.code == code)) is not None

    def active_child_exists(self, db: Session, category_id: UUID) -> bool:
        return db.scalar(
            select(ExpenseCategory.id)
            .where(
                ExpenseCategory.parent_id == category_id,
                ExpenseCategory.is_active.is_(True),
            )
            .limit(1)
        ) is not None

    def expense_for_update(self, db: Session, expense_id: UUID) -> Expense | None:
        return db.scalar(select(Expense).where(Expense.id == expense_id).with_for_update())

    def attachment_count(self, db: Session, expense_id: UUID) -> int:
        return int(
            db.scalar(
                select(func.count(ExpenseAttachment.id)).where(
                    ExpenseAttachment.expense_id == expense_id
                )
            )
            or 0
        )

    def list_attachments(
        self, db: Session, expense_id: UUID
    ) -> list[tuple[ExpenseAttachment, FileRecord]]:
        return list(
            db.execute(
                select(ExpenseAttachment, FileRecord)
                .join(FileRecord, FileRecord.id == ExpenseAttachment.file_id)
                .where(
                    ExpenseAttachment.expense_id == expense_id,
                    FileRecord.status == FileStatus.ACTIVE,
                )
                .order_by(ExpenseAttachment.created_at)
            ).all()
        )

    def attachment(
        self, db: Session, expense_id: UUID, file_id: UUID
    ) -> tuple[ExpenseAttachment, FileRecord] | None:
        return db.execute(
            select(ExpenseAttachment, FileRecord)
            .join(FileRecord, FileRecord.id == ExpenseAttachment.file_id)
            .where(
                ExpenseAttachment.expense_id == expense_id,
                ExpenseAttachment.file_id == file_id,
                FileRecord.status == FileStatus.ACTIVE,
            )
        ).one_or_none()

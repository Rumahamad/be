from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.expenses import ExpenseCategory
from app.models.identity import User
from app.repositories.expenses import ExpenseRepository
from app.schemas.expenses import (
    CreateExpenseCategoryInput,
    ExpenseCategoryOutput,
    UpdateExpenseCategoryInput,
)
from app.services.audit_service import AuditService


class ExpenseCategoryService:
    def __init__(self, repository: ExpenseRepository | None = None) -> None:
        self.repository = repository or ExpenseRepository()
        self.audit = AuditService()

    def list(
        self, db: Session, *, include_inactive: bool
    ) -> list[ExpenseCategoryOutput]:
        return [self.output(item) for item in self.repository.list_categories(
            db, include_inactive=include_inactive
        )]

    def create(
        self, db: Session, actor: User, payload: CreateExpenseCategoryInput
    ) -> ExpenseCategoryOutput:
        if self.repository.code_exists(db, payload.code):
            raise HTTPException(status_code=409, detail="Expense category code already exists")
        if payload.parent_id:
            parent = self.repository.get_category(db, payload.parent_id)
            if not parent:
                raise HTTPException(status_code=422, detail="Parent expense category not found")
            if not parent.is_active:
                raise HTTPException(status_code=409, detail="Parent expense category is inactive")
        category = ExpenseCategory(
            code=payload.code,
            name=payload.name,
            description=payload.description.strip() if payload.description else None,
            parent_id=payload.parent_id,
            sort_order=payload.sort_order,
            is_active=True,
            created_by=actor.id,
        )
        db.add(category)
        db.flush()
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="expense_category.created",
            entity_type="expense_category",
            entity_id=category.id,
            after_data={"code": category.code, "name": category.name},
        )
        db.commit()
        db.refresh(category)
        return self.output(category)

    def update(
        self,
        db: Session,
        actor: User,
        category_id: UUID,
        payload: UpdateExpenseCategoryInput,
    ) -> ExpenseCategoryOutput:
        category = self.repository.get_category(db, category_id, for_update=True)
        if not category:
            raise HTTPException(status_code=404, detail="Expense category not found")
        changes = payload.model_dump(exclude_unset=True)
        parent_id = changes.get("parent_id", category.parent_id)
        is_active = changes.get("is_active", category.is_active)
        self._validate_parent(db, category, parent_id, is_active)
        if changes.get("is_active") is False and self.repository.active_child_exists(db, category.id):
            raise HTTPException(
                status_code=409, detail="Deactivate or move active child categories first"
            )
        before = {key: self._audit_value(getattr(category, key)) for key in changes}
        for key, value in changes.items():
            if key == "description" and isinstance(value, str):
                value = value.strip() or None
            setattr(category, key, value)
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="expense_category.updated",
            entity_type="expense_category",
            entity_id=category.id,
            before_data=before,
            after_data={key: self._audit_value(getattr(category, key)) for key in changes},
        )
        db.commit()
        db.refresh(category)
        return self.output(category)

    def _validate_parent(
        self,
        db: Session,
        category: ExpenseCategory,
        parent_id: UUID | None,
        is_active: bool,
    ) -> None:
        visited = {category.id}
        current_id = parent_id
        while current_id:
            if current_id in visited:
                raise HTTPException(status_code=409, detail="Expense category hierarchy contains a cycle")
            visited.add(current_id)
            parent = self.repository.get_category(db, current_id)
            if not parent:
                raise HTTPException(status_code=422, detail="Parent expense category not found")
            if is_active and not parent.is_active:
                raise HTTPException(status_code=409, detail="Active category cannot have an inactive parent")
            current_id = parent.parent_id

    @staticmethod
    def output(category: ExpenseCategory) -> ExpenseCategoryOutput:
        return ExpenseCategoryOutput.model_validate(category, from_attributes=True)

    @staticmethod
    def _audit_value(value: object) -> object:
        return str(value) if isinstance(value, UUID) else value

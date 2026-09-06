from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import UserStatus
from app.schemas.members import CreateMemberInput
from app.services.member_service import MemberService
from app.services.supabase_admin_service import CreatedAuthUser


class FakeDatabase:
    def __init__(self, member=None):
        self.member = member
        self.added = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    def flush(self):
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        return None

    def refresh(self, value):
        return None

    def get(self, model, member_id):
        return self.member if self.member and self.member.id == member_id else None


class FakeMembers:
    def __init__(self, creator_role: str):
        self.creator_role = creator_role
        self.role = SimpleNamespace(id=uuid4(), code="MEMBER")

    def active_role(self, db, code):
        self.role.code = code
        return self.role

    def role_code(self, db, role_id):
        return self.creator_role

    def next_member_code(self, db):
        return "BNC-999"


class FakeAuthAdmin:
    def __init__(self):
        self.invites = []

    def invite_user(self, email, display_name, redirect_to):
        self.invites.append((email, display_name, redirect_to))
        return CreatedAuthUser(id=uuid4(), email=email)

    def delete_user(self, auth_user_id):
        return None


class FakeAudit:
    def record(self, *args, **kwargs):
        return None


def service_for(creator_role: str) -> MemberService:
    service = MemberService()
    service.members = FakeMembers(creator_role)
    service.auth_admin = FakeAuthAdmin()
    service.audit = FakeAudit()
    return service


def member_input(role_code="MEMBER") -> CreateMemberInput:
    return CreateMemberInput(
        email="new.member@example.com",
        first_name="New",
        last_name="Member",
        role_code=role_code,
    )


def test_committee_created_member_waits_for_admin_without_invitation() -> None:
    service = service_for("COMMITTEE")

    member = service.create(
        FakeDatabase(),
        SimpleNamespace(id=uuid4(), role_id=uuid4()),
        member_input(),
    )

    assert member.status == UserStatus.INACTIVE
    assert member.auth_user_id is None
    assert service.auth_admin.invites == []


def test_committee_cannot_assign_committee_role() -> None:
    service = service_for("COMMITTEE")

    with pytest.raises(ValueError, match="Only Admin"):
        service.create(
            FakeDatabase(),
            SimpleNamespace(id=uuid4(), role_id=uuid4()),
            member_input("COMMITTEE"),
        )


def test_admin_approval_sends_invitation_and_activates_member() -> None:
    service = service_for("ADMIN")
    member = SimpleNamespace(
        id=uuid4(),
        email="pending@example.com",
        display_name="Pending Member",
        auth_user_id=None,
        password_setup_required=True,
        status=UserStatus.INACTIVE,
    )
    db = FakeDatabase(member)

    updated = service.set_status(
        db,
        SimpleNamespace(id=uuid4()),
        member.id,
        UserStatus.ACTIVE,
    )

    assert updated.status == UserStatus.ACTIVE
    assert updated.auth_user_id is not None
    assert len(service.auth_admin.invites) == 1
    assert db.commits == 1

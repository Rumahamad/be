from uuid import uuid4

from app.schemas.administration import CreateGroupInput, SetGroupMembersInput


def test_group_code_is_normalized() -> None:
    payload = CreateGroupInput(name="Relief Team", code=" relief team ")

    assert payload.name == "Relief Team"
    assert payload.code == "RELIEF-TEAM"


def test_group_members_accept_empty_list_for_clear_operation() -> None:
    payload = SetGroupMembersInput(member_ids=[])

    assert payload.member_ids == []
    assert SetGroupMembersInput(member_ids=[uuid4()]).member_ids

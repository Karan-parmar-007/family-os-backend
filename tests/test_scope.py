from uuid import uuid4

from app.core.scope import (
    ScopeContext,
    can_edit_scoped_entity,
    can_view_scoped_entity,
    filter_entity_rows,
    owner_user_id_for_row,
)


class _Row:
    def __init__(
        self,
        *,
        scope_type: str = "FAMILY",
        access_level: str = "FAMILY",
        user_id=None,
        debt_in_the_name_of=None,
    ):
        self.scope_type = scope_type
        self.access_level = access_level
        self.user_id = user_id
        self.debt_in_the_name_of = debt_in_the_name_of


def _ctx(**kwargs) -> ScopeContext:
    defaults = dict(
        user_id=uuid4(),
        family_id=uuid4(),
        is_family_manager=False,
    )
    defaults.update(kwargs)
    return ScopeContext(**defaults)


def test_owner_sees_private_personal_row():
    user_id = uuid4()
    ctx = _ctx(user_id=user_id)
    row = _Row(access_level="PRIVATE", user_id=user_id)
    assert can_view_scoped_entity(
        ctx,
        scope_type="FAMILY",
        owner_user_id=owner_user_id_for_row(row, is_personal=True),
        access_level=row.access_level,
    )


def test_non_owner_cannot_see_private():
    ctx = _ctx()
    row = _Row(access_level="PRIVATE", user_id=uuid4())
    assert not can_view_scoped_entity(
        ctx,
        scope_type="FAMILY",
        owner_user_id=owner_user_id_for_row(row, is_personal=True),
        access_level=row.access_level,
    )


def test_family_rows_remain_visible_to_family_scope():
    ctx = _ctx()
    row = _Row(scope_type="FAMILY", access_level="FAMILY")
    assert filter_entity_rows(ctx, [(row, False)]) == [(row, False)]


def test_family_manager_can_edit_family_scoped_row():
    ctx = _ctx(is_family_manager=True)
    row = _Row(access_level="FAMILY")
    assert can_edit_scoped_entity(
        ctx,
        scope_type="FAMILY",
        owner_user_id=None,
        access_level=row.access_level,
    )


def test_non_manager_cannot_edit_others_private():
    ctx = _ctx(is_family_manager=False)
    assert not can_edit_scoped_entity(
        ctx,
        scope_type="FAMILY",
        owner_user_id=uuid4(),
        access_level="PRIVATE",
    )

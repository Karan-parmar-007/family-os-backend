"""Scope and membership context for Family System V2 access resolution."""

from dataclasses import dataclass, field
from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.user.model import UserFamilyLink
from app.core.constants import (
    ACCESS_SELECTED,
    SOURCE_LINKED_EXPENSE_LOG,
    SOURCE_LINKED_INCOME_LOG,
)


@dataclass
class ScopeContext:
    user_id: UUID
    family_id: UUID
    is_family_manager: bool = False
    shared_entity_ids: set[UUID] = field(default_factory=set)


async def load_scope_context(
    session: AsyncSession,
    user_id: UUID,
    family_id: UUID,
) -> ScopeContext | None:
    link_stmt = select(UserFamilyLink).where(
        UserFamilyLink.user_id == user_id,
        UserFamilyLink.family_id == family_id,
    )
    link = (await session.execute(link_stmt)).scalar_one_or_none()
    if link is None:
        return None

    return ScopeContext(
        user_id=user_id,
        family_id=family_id,
        is_family_manager=link.is_family_manager,
    )


def can_view_scoped_entity(
    ctx: ScopeContext,
    *,
    scope_type: str,
    owner_user_id: UUID | None = None,
    access_level: str = "FAMILY",
    entity_id: UUID | None = None,
) -> bool:
    if owner_user_id == ctx.user_id:
        return True

    if access_level == "PRIVATE":
        return owner_user_id == ctx.user_id
    if access_level == "FAMILY":
        return True
    if access_level == ACCESS_SELECTED:
        return entity_id is not None and entity_id in ctx.shared_entity_ids
    return False


def can_edit_scoped_entity(
    ctx: ScopeContext,
    *,
    scope_type: str,
    owner_user_id: UUID | None = None,
    access_level: str = "FAMILY",
) -> bool:
    if owner_user_id == ctx.user_id:
        return True
    if ctx.is_family_manager:
        return access_level != "PRIVATE" or owner_user_id == ctx.user_id
    return False


T = TypeVar("T")


def filter_visible(
    ctx: ScopeContext,
    rows: list[T],
    *,
    scope_type_getter,
    owner_user_id_getter=lambda r: None,
    access_level_getter=lambda r: "FAMILY",
) -> list[T]:
    return [
        row
        for row in rows
        if can_view_scoped_entity(
            ctx,
            scope_type=scope_type_getter(row),
            owner_user_id=owner_user_id_getter(row),
            access_level=access_level_getter(row),
        )
    ]


def assert_can_view(ctx: ScopeContext, **kwargs) -> None:
    if not can_view_scoped_entity(ctx, **kwargs):
        raise PermissionError("Not allowed to view this resource")


def assert_can_edit(ctx: ScopeContext, **kwargs) -> None:
    if not can_edit_scoped_entity(ctx, **kwargs):
        raise PermissionError("Not allowed to edit this resource")


def owner_user_id_for_row(row: object, *, is_personal: bool) -> UUID | None:
    if is_personal:
        return getattr(row, "user_id", None) or getattr(row, "in_someone_name", None)
    return getattr(row, "debt_in_the_name_of", None) or getattr(row, "in_someone_name", None)


def filter_entity_rows(
    ctx: ScopeContext | None,
    rows: list[tuple[T, bool]],
) -> list[tuple[T, bool]]:
    if ctx is None:
        return rows
    return [
        (row, is_personal)
        for row, is_personal in rows
        if can_view_scoped_entity(
            ctx,
            scope_type=row.scope_type,
            owner_user_id=owner_user_id_for_row(row, is_personal=is_personal),
            access_level=getattr(row, "access_level", "FAMILY"),
            entity_id=getattr(row, "id", None),
        )
    ]


def assert_entity_visible(ctx: ScopeContext, row: object, *, is_personal: bool) -> None:
    assert_can_view(
        ctx,
        scope_type=row.scope_type,
        owner_user_id=owner_user_id_for_row(row, is_personal=is_personal),
        access_level=getattr(row, "access_level", "FAMILY"),
        entity_id=getattr(row, "id", None),
    )


def assert_entity_editable(ctx: ScopeContext, row: object, *, is_personal: bool) -> None:
    assert_can_edit(
        ctx,
        scope_type=row.scope_type,
        owner_user_id=owner_user_id_for_row(row, is_personal=is_personal),
        access_level=getattr(row, "access_level", "FAMILY"),
    )


def assert_income_log_visible(ctx: ScopeContext, log) -> None:
    if not can_view_income_log(ctx, log):
        raise PermissionError("Not allowed to view this resource")


def can_view_income_log(ctx: ScopeContext, log) -> bool:
    if getattr(log, "source_type", None) == SOURCE_LINKED_INCOME_LOG:
        return True
    access = "FAMILY" if getattr(log, "show_doc_to_all", False) else "PRIVATE"
    return can_view_scoped_entity(
        ctx,
        scope_type=log.scope_type,
        owner_user_id=log.earned_by_user_id or log.logged_by,
        access_level=access,
        entity_id=getattr(log, "id", None),
    )


async def require_entity_visible(
    session: AsyncSession,
    user_id: UUID,
    family_id: UUID,
    row: object,
    *,
    is_personal: bool,
) -> ScopeContext | None:
    ctx = await load_scope_context(session, user_id, family_id)
    if ctx is not None:
        assert_entity_visible(ctx, row, is_personal=is_personal)
    return ctx


async def require_income_log_visible(
    session: AsyncSession,
    user_id: UUID,
    family_id: UUID,
    log: object,
) -> ScopeContext | None:
    ctx = await load_scope_context(session, user_id, family_id)
    if ctx is not None:
        assert_income_log_visible(ctx, log)
    return ctx


def can_view_expense_log(ctx: ScopeContext, log) -> bool:
    if getattr(log, "source_type", None) == SOURCE_LINKED_EXPENSE_LOG:
        return True
    access = "FAMILY" if getattr(log, "show_doc_to_all", False) else "PRIVATE"
    return can_view_scoped_entity(
        ctx,
        scope_type=log.scope_type,
        owner_user_id=getattr(log, "personal_savings_user_id", None) or log.logged_by,
        access_level=access,
        entity_id=getattr(log, "id", None),
    )


def assert_expense_log_visible(ctx: ScopeContext, log) -> None:
    if not can_view_expense_log(ctx, log):
        raise PermissionError("Not allowed to view this resource")


async def require_expense_log_visible(
    session: AsyncSession,
    user_id: UUID,
    family_id: UUID,
    log: object,
) -> ScopeContext | None:
    ctx = await load_scope_context(session, user_id, family_id)
    if ctx is not None:
        assert_expense_log_visible(ctx, log)
    return ctx


async def require_entity_editable(
    session: AsyncSession,
    user_id: UUID,
    family_id: UUID,
    row: object,
    *,
    is_personal: bool,
) -> ScopeContext | None:
    ctx = await load_scope_context(session, user_id, family_id)
    if ctx is not None:
        assert_entity_editable(ctx, row, is_personal=is_personal)
    return ctx

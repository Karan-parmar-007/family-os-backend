"""Helpers for multi-family income/expense log splits."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.expense.model import FamilyExpenseLog
from app.api.routes.family.model import LogFundingSource
from app.api.routes.family_income.model import FamilyIncomeLog
from app.api.schemas.funding import FundingSourceInput
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_EXPENSE_LOG,
    LEDGER_SOURCE_INCOME_LOG,
    POOL_FAMILY,
    SOURCE_LINKED_EXPENSE_LOG,
    SOURCE_LINKED_INCOME_LOG,
)
from app.core.funding_sources import pool_ref_from_funding_source
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef


async def fetch_log_funding_sources(
    session: AsyncSession,
    entity_type: str,
    log_id: UUID,
) -> list[FundingSourceInput]:
    stmt = select(LogFundingSource).where(
        LogFundingSource.entity_type == entity_type,
        LogFundingSource.entity_id == log_id,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        FundingSourceInput(
            pool_type=row.pool_type,
            family_id=row.family_id,
            user_id=row.user_id,
            amount=row.amount,
        )
        for row in rows
    ]


async def create_linked_income_logs(
    session: AsyncSession,
    ledger: SavingsLedgerService,
    *,
    primary_log_id: UUID,
    primary_family_id: UUID,
    logged_by_user_id: UUID,
    income_name: str,
    income_date,
    document_id: UUID | None,
    show_doc_to_all: bool,
    funding_sources: list[FundingSourceInput],
) -> list[UUID]:
    """Create income logs + savings credits for other families in a split."""
    affected_family_ids: list[UUID] = []
    for source in funding_sources:
        if source.pool_type != POOL_FAMILY:
            continue
        if source.family_id is None or source.family_id == primary_family_id:
            continue

        linked = FamilyIncomeLog(
            family_id=source.family_id,
            logged_by=logged_by_user_id,
            income_name=income_name,
            total_amount=source.amount,
            family_amount=source.amount,
            income_date=income_date,
            source_type=SOURCE_LINKED_INCOME_LOG,
            source_id=primary_log_id,
            earned_by_user_id=logged_by_user_id,
            document_id=document_id,
            added_by_user_id=logged_by_user_id,
            show_doc_to_all=True,
            let_everyone_edit=False,
        )
        session.add(linked)
        await session.flush()

        await ledger.apply_movement(
            SavingsPoolRef(pool_type=POOL_FAMILY, family_id=source.family_id),
            source.amount,
            LEDGER_IN,
            LEDGER_SOURCE_INCOME_LOG,
            source_id=linked.id,
        )
        affected_family_ids.append(source.family_id)
    return affected_family_ids


async def create_linked_expense_logs(
    session: AsyncSession,
    ledger: SavingsLedgerService,
    *,
    primary_log_id: UUID,
    primary_family_id: UUID,
    logged_by_user_id: UUID,
    expense_name: str,
    expense_date,
    document_id: UUID | None,
    show_doc_to_all: bool,
    funding_sources: list[FundingSourceInput],
) -> list[UUID]:
    """Create expense logs + savings debits for other families in a split."""
    affected_family_ids: list[UUID] = []
    for source in funding_sources:
        if source.pool_type != POOL_FAMILY:
            continue
        if source.family_id is None or source.family_id == primary_family_id:
            continue

        linked = FamilyExpenseLog(
            family_id=source.family_id,
            logged_by=logged_by_user_id,
            expense_name=expense_name,
            amount=source.amount,
            total_amount=source.amount,
            family_amount=source.amount,
            expense_date=expense_date,
            source_type=SOURCE_LINKED_EXPENSE_LOG,
            source_id=primary_log_id,
            document_id=document_id,
            added_by_user_id=logged_by_user_id,
            show_doc_to_all=True,
            let_everyone_edit=False,
        )
        session.add(linked)
        await session.flush()

        await ledger.apply_movement(
            SavingsPoolRef(pool_type=POOL_FAMILY, family_id=source.family_id),
            source.amount,
            LEDGER_OUT,
            LEDGER_SOURCE_EXPENSE_LOG,
            source_id=linked.id,
        )
        affected_family_ids.append(source.family_id)
    return affected_family_ids


def resolve_let_everyone_edit(
    requested: bool,
    funding_sources: list[FundingSourceInput] | None,
    primary_family_id: UUID,
    personal_amount: Decimal | None,
) -> bool:
    if not requested:
        return False
    if personal_amount and personal_amount > 0:
        return False
    if not funding_sources:
        return True
    other_families = [
        s
        for s in funding_sources
        if s.pool_type == POOL_FAMILY and s.family_id is not None and s.family_id != primary_family_id
    ]
    return len(other_families) == 0


def is_other_family_source(source: FundingSourceInput, primary_family_id: UUID) -> bool:
    return (
        source.pool_type == POOL_FAMILY
        and source.family_id is not None
        and source.family_id != primary_family_id
    )


async def replace_primary_log_funding(
    session: AsyncSession,
    ledger: SavingsLedgerService,
    *,
    entity_type: str,
    entity_id: UUID,
    primary_family_id: UUID,
    actor_user_id: UUID,
    old_sources: list[FundingSourceInput],
    new_sources: list[FundingSourceInput],
    apply_direction: str,
    ledger_source_type: str,
) -> None:
    """Reverse old primary-family/personal funding, then apply and persist new sources.

    Other-family rows are skipped here (handled via linked logs).
    """
    reverse_direction = LEDGER_OUT if apply_direction == LEDGER_IN else LEDGER_IN

    for source in old_sources:
        if is_other_family_source(source, primary_family_id):
            continue
        pool = pool_ref_from_funding_source(actor_user_id, source)
        await ledger.apply_movement(
            pool,
            source.amount,
            reverse_direction,
            ledger_source_type,
            source_id=entity_id,
        )

    await session.execute(
        delete(LogFundingSource).where(
            LogFundingSource.entity_type == entity_type,
            LogFundingSource.entity_id == entity_id,
        )
    )
    await session.flush()

    for source in new_sources:
        if is_other_family_source(source, primary_family_id):
            continue
        pool = pool_ref_from_funding_source(actor_user_id, source)
        await ledger.apply_movement(
            pool,
            source.amount,
            apply_direction,
            ledger_source_type,
            source_id=entity_id,
        )
        session.add(
            LogFundingSource(
                entity_type=entity_type,
                entity_id=entity_id,
                direction=apply_direction,
                pool_type=source.pool_type,
                family_id=source.family_id,
                user_id=source.user_id,
                amount=source.amount,
            )
        )
    await session.flush()


async def remove_linked_income_logs(
    session: AsyncSession,
    ledger: SavingsLedgerService,
    *,
    primary_log_id: UUID,
) -> None:
    """Reverse savings and delete linked income logs created from a multi-family split."""
    stmt = select(FamilyIncomeLog).where(
        FamilyIncomeLog.source_type == SOURCE_LINKED_INCOME_LOG,
        FamilyIncomeLog.source_id == primary_log_id,
    )
    linked_logs = list((await session.execute(stmt)).scalars().all())
    for linked in linked_logs:
        amount = linked.family_amount or linked.total_amount or Decimal("0")
        if amount > 0:
            await ledger.apply_movement(
                SavingsPoolRef(pool_type=POOL_FAMILY, family_id=linked.family_id),
                amount,
                LEDGER_OUT,
                LEDGER_SOURCE_INCOME_LOG,
                source_id=linked.id,
            )
        await session.delete(linked)
    await session.flush()


async def remove_linked_expense_logs(
    session: AsyncSession,
    ledger: SavingsLedgerService,
    *,
    primary_log_id: UUID,
) -> None:
    """Reverse savings and delete linked expense logs created from a multi-family split."""
    stmt = select(FamilyExpenseLog).where(
        FamilyExpenseLog.source_type == SOURCE_LINKED_EXPENSE_LOG,
        FamilyExpenseLog.source_id == primary_log_id,
    )
    linked_logs = list((await session.execute(stmt)).scalars().all())
    for linked in linked_logs:
        amount = linked.family_amount or linked.total_amount or Decimal("0")
        if amount > 0:
            await ledger.apply_movement(
                SavingsPoolRef(pool_type=POOL_FAMILY, family_id=linked.family_id),
                amount,
                LEDGER_IN,
                LEDGER_SOURCE_EXPENSE_LOG,
                source_id=linked.id,
            )
        await session.delete(linked)
    await session.flush()

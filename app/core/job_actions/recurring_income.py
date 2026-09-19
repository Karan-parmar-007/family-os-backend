"""RECURRING_INCOME job action handlers (Plan 12)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family_income.model import (
    FamilyIncomeLog,
    PersonalIncomeLog,
    RecurringIncome,
    RecurringIncomeFamilySplit,
)
from app.api.routes.scheduler.model import ScheduledJob
from app.api.routes.user.model import UserFamilyLink
from app.core.constants import (
    JOB_STATUS_APPLIED,
    LEDGER_IN,
    LEDGER_SOURCE_RECURRING_INCOME,
    POOL_FAMILY,
    POOL_PERSONAL,
)
from app.core.date_advance import advance_next_date
from app.core.job_actions.validators import validate_income_allocations
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef


async def apply_adjusted_income(
    session: AsyncSession,
    job: ScheduledJob,
    payload: dict,
) -> None:
    """Apply income with caller-provided amounts for this period only."""
    new_amount_raw = payload.get("newAmount") or payload.get("new_amount")
    if new_amount_raw is None:
        raise ValueError("ADJUST_AMOUNT requires payload.newAmount")
    new_total = Decimal(str(new_amount_raw))

    income = (
        await session.execute(
            select(RecurringIncome).where(RecurringIncome.id == job.source_id)
        )
    ).scalar_one_or_none()
    if income is None or income.next_receiving_date is None:
        raise ValueError("Recurring income not found or inactive")

    splits = list(
        (
            await session.execute(
                select(RecurringIncomeFamilySplit).where(
                    RecurringIncomeFamilySplit.income_id == income.id
                )
            )
        ).scalars().all()
    )
    allowed_families = {s.family_id for s in splits}

    personal_raw = payload.get("personalAmount") or payload.get("personal_amount")
    if personal_raw is not None:
        personal_amount = Decimal(str(personal_raw))
    else:
        personal_amount = income.personal_savings_amount or Decimal("0")

    allocations = payload.get("incomeAllocations") or payload.get("income_allocations")
    if allocations:
        validate_income_allocations(
            allocations,
            personal_amount,
            new_total,
            allowed_family_ids=allowed_families,
        )
        alloc_by_family: dict[UUID, Decimal] = {}
        for row in allocations:
            fid = UUID(str(row.get("familyId") or row.get("family_id")))
            alloc_by_family[fid] = Decimal(str(row.get("amount", "0")))
    else:
        # Scale stored splits proportionally to new total
        stored_total = sum((s.amount for s in splits), Decimal("0")) + (
            income.personal_savings_amount or Decimal("0")
        )
        if stored_total <= 0:
            raise ValueError("Cannot adjust income with zero stored total")
        ratio = new_total / stored_total
        alloc_by_family = {s.family_id: (s.amount * ratio).quantize(Decimal("0.01")) for s in splits}
        personal_amount = (personal_amount * ratio).quantize(Decimal("0.01"))
        # Fix rounding drift
        drift = new_total - (sum(alloc_by_family.values()) + personal_amount)
        if drift != 0 and splits:
            alloc_by_family[splits[0].family_id] += drift

    member_families = set(
        (
            await session.execute(
                select(UserFamilyLink.family_id).where(
                    UserFamilyLink.user_id == income.user_id
                )
            )
        ).scalars().all()
    )

    when = datetime.now(timezone.utc)
    ledger = SavingsLedgerService(session)
    first_log_id: UUID | None = None
    split_by_family = {s.family_id: s for s in splits}

    for family_id, amount in alloc_by_family.items():
        if family_id not in member_families:
            continue
        split = split_by_family.get(family_id)
        if split is None:
            continue
        log = FamilyIncomeLog(
            family_id=family_id,
            scope_type="FAMILY",
            logged_by=income.user_id,
            income_name=split.split_name,
            total_amount=amount,
            family_amount=amount,
            income_date=when,
            source_type="RECURRING",
            source_id=income.id,
            recurring_income_family_split_id=split.id,
            earned_by_user_id=income.user_id,
            category_id=income.category_id,
            document_id=income.document_id if income.repeat_doc_with_logs else None,
            added_by_user_id=income.user_id,
            show_doc_to_all=income.show_docs_to_all,
        )
        session.add(log)
        await session.flush()
        if first_log_id is None:
            first_log_id = log.id
        if amount > 0:
            await ledger.apply_movement(
                SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_id),
                amount,
                LEDGER_IN,
                LEDGER_SOURCE_RECURRING_INCOME,
                source_id=log.id,
                occurred_at=when,
            )

    if personal_amount > 0:
        personal_source_id = first_log_id or job.id
        await ledger.apply_movement(
            SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=income.user_id),
            personal_amount,
            LEDGER_IN,
            LEDGER_SOURCE_RECURRING_INCOME,
            source_id=personal_source_id,
            occurred_at=when,
        )
        if splits and first_log_id is not None:
            session.add(
                PersonalIncomeLog(
                    family_id=splits[0].family_id,
                    user_id=income.user_id,
                    logged_by=income.user_id,
                    income_name=income.income_name,
                    amount=personal_amount,
                    income_date=when,
                    source_type="RECURRING",
                    source_id=income.id,
                    category_id=income.category_id,
                    document_id=income.document_id if income.repeat_doc_with_logs else None,
                    show_doc_to_all=income.show_docs_to_all,
                )
            )
            await session.flush()

    income.next_receiving_date = advance_next_date(
        income.next_receiving_date,
        every=income.received_every,
        interval_days=income.repeat_interval_days,
        interval_months=income.repeat_interval_months,
        interval_years=income.repeat_interval_years,
    )
    from app.scheduler.income_cron import create_or_replace_next_job

    await create_or_replace_next_job(session, income)
    job.applied_ledger_id = first_log_id
    job.status = JOB_STATUS_APPLIED

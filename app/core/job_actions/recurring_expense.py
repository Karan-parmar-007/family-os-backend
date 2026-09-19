"""RECURRING_EXPENSE job action handlers (Plan 12)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.expense.model import FamilyExpenseLog, PersonalExpenseLog
from app.api.routes.family_expense.model import (
    RecurringExpense,
    RecurringExpenseFamilySplit,
)
from app.api.routes.scheduler.model import ScheduledJob
from app.api.routes.user.model import UserFamilyLink
from app.core.constants import (
    JOB_STATUS_APPLIED,
    JOB_STATUS_SKIPPED,
    LEDGER_OUT,
    LEDGER_SOURCE_EMI,
    LEDGER_SOURCE_RECURRING_EXPENSE,
    POOL_FAMILY,
    POOL_PERSONAL,
)
from app.core.date_advance import advance_next_date
from app.core.funding_service import FundingService, SplitLine
from app.core.job_actions.validators import validate_split_lines
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef


async def apply_adjusted_expense(
    session: AsyncSession,
    job: ScheduledJob,
    payload: dict,
) -> None:
    new_amount_raw = payload.get("newAmount") or payload.get("new_amount")
    if new_amount_raw is None:
        raise ValueError("ADJUST_AMOUNT requires payload.newAmount")
    new_total = Decimal(str(new_amount_raw))

    expense_sources = payload.get("expenseSources") or payload.get("expense_sources")
    if expense_sources:
        await apply_expense_with_sources(session, job, new_total, expense_sources)
        return

    expense = (
        await session.execute(
            select(RecurringExpense).where(RecurringExpense.id == job.source_id)
        )
    ).scalar_one_or_none()
    if expense is None or expense.next_payment_date is None:
        raise ValueError("Recurring expense not found or inactive")

    splits = list(
        (
            await session.execute(
                select(RecurringExpenseFamilySplit).where(
                    RecurringExpenseFamilySplit.expense_id == expense.id
                )
            )
        ).scalars().all()
    )
    stored_total = sum((s.amount for s in splits), Decimal("0")) + (
        expense.personal_savings_amount or Decimal("0")
    )
    if stored_total <= 0:
        raise ValueError("Cannot adjust expense with zero stored total")
    ratio = new_total / stored_total

    member_families = set(
        (
            await session.execute(
                select(UserFamilyLink.family_id).where(
                    UserFamilyLink.user_id == expense.user_id
                )
            )
        ).scalars().all()
    )
    when = datetime.now(timezone.utc)
    ledger = SavingsLedgerService(session)
    first_log_id: UUID | None = None

    for split in splits:
        if split.family_id not in member_families:
            continue
        amount = (split.amount * ratio).quantize(Decimal("0.01"))
        log = FamilyExpenseLog(
            family_id=split.family_id,
            scope_type="FAMILY",
            logged_by=expense.user_id,
            expense_name=split.split_name,
            amount=amount,
            total_amount=amount,
            family_amount=amount,
            expense_date=when,
            source_type="RECURRING",
            source_id=expense.id,
            recurring_expense_family_split_id=split.id,
            category_id=expense.category_id,
            document_id=expense.document_id if expense.repeat_doc_with_logs else None,
            added_by_user_id=expense.user_id,
            show_doc_to_all=expense.show_docs_to_all,
        )
        session.add(log)
        await session.flush()
        if first_log_id is None:
            first_log_id = log.id
        if amount > 0:
            await ledger.apply_movement(
                SavingsPoolRef(pool_type=POOL_FAMILY, family_id=split.family_id),
                amount,
                LEDGER_OUT,
                LEDGER_SOURCE_RECURRING_EXPENSE,
                source_id=log.id,
                occurred_at=when,
            )

    personal_amount = ((expense.personal_savings_amount or Decimal("0")) * ratio).quantize(
        Decimal("0.01")
    )
    if personal_amount > 0:
        personal_source_id = first_log_id or job.id
        await ledger.apply_movement(
            SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=expense.user_id),
            personal_amount,
            LEDGER_OUT,
            LEDGER_SOURCE_RECURRING_EXPENSE,
            source_id=personal_source_id,
            occurred_at=when,
        )
        if splits and first_log_id is not None:
            session.add(
                PersonalExpenseLog(
                    family_id=splits[0].family_id,
                    user_id=expense.user_id,
                    logged_by=expense.user_id,
                    expense_name=expense.expense_name,
                    amount=personal_amount,
                    expense_date=when,
                    source_type="RECURRING",
                    source_id=expense.id,
                    category_id=expense.category_id,
                    document_id=expense.document_id if expense.repeat_doc_with_logs else None,
                    show_doc_to_all=expense.show_docs_to_all,
                )
            )
            await session.flush()

    expense.next_payment_date = advance_next_date(
        expense.next_payment_date,
        every=expense.paid_every,
        interval_days=expense.repeat_interval_days,
        interval_months=expense.repeat_interval_months,
        interval_years=expense.repeat_interval_years,
    )
    from app.scheduler.expense_cron import create_or_replace_next_job

    await create_or_replace_next_job(session, expense)
    job.applied_ledger_id = first_log_id
    job.status = JOB_STATUS_APPLIED


async def apply_expense_with_sources(
    session: AsyncSession,
    job: ScheduledJob,
    amount: Decimal,
    sources: list[dict],
) -> None:
    validate_split_lines(sources, amount)
    fs = FundingService(session)
    lines = [
        SplitLine(
            pool_type=ln["poolType"] if "poolType" in ln else ln["pool_type"],
            amount=Decimal(str(ln["amount"])),
            family_id=ln.get("familyId") or ln.get("family_id"),
            user_id=ln.get("userId") or ln.get("user_id"),
        )
        for ln in sources
    ]
    await fs.execute_debit(
        lines,
        amount,
        ledger_source_type=LEDGER_SOURCE_EMI,
        entity_type=job.source_type,
        entity_id=job.source_id,
        job_id=job.id,
        description=f"Split-accepted expense for job {job.id}",
    )
    expense = (
        await session.execute(
            select(RecurringExpense).where(RecurringExpense.id == job.source_id)
        )
    ).scalar_one_or_none()
    if expense and expense.next_payment_date:
        expense.next_payment_date = advance_next_date(
            expense.next_payment_date,
            every=expense.paid_every,
            interval_days=expense.repeat_interval_days,
            interval_months=expense.repeat_interval_months,
            interval_years=expense.repeat_interval_years,
        )
        from app.scheduler.expense_cron import create_or_replace_next_job

        await create_or_replace_next_job(session, expense)
    job.status = JOB_STATUS_APPLIED


async def apply_paid_externally(session: AsyncSession, job: ScheduledJob) -> None:
    fs = FundingService(session)
    await fs.execute_paid_externally(
        entity_type=job.source_type,
        entity_id=job.source_id,
        amount=job.amount,
        job_id=job.id,
        description="Paid externally",
    )
    expense = (
        await session.execute(
            select(RecurringExpense).where(RecurringExpense.id == job.source_id)
        )
    ).scalar_one_or_none()
    if expense and expense.next_payment_date:
        expense.next_payment_date = advance_next_date(
            expense.next_payment_date,
            every=expense.paid_every,
            interval_days=expense.repeat_interval_days,
            interval_months=expense.repeat_interval_months,
            interval_years=expense.repeat_interval_years,
        )
        from app.scheduler.expense_cron import create_or_replace_next_job

        await create_or_replace_next_job(session, expense)
    job.status = JOB_STATUS_SKIPPED

"""Per-job-type apply handlers (Family System V2)."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.debt.model import Debt
from app.api.routes.family_income.model import (
    FamilyIncomeLog,
    PersonalIncomeLog,
    RecurringIncome,
    RecurringIncomeFamilySplit,
    RecurringIncomePersonalSplit,
)
from app.api.routes.family_expense.model import (
    RecurringExpense,
    RecurringExpenseFamilySplit,
    RecurringExpensePersonalSplit,
)
from app.api.routes.expense.model import (
    FamilyExpense,
    FamilyExpenseLog,
    PersonalExpense,
    PersonalExpenseLog,
)
from app.api.routes.goals.model import FamilyGoal, PersonalGoal
from app.api.routes.assets.model import FamilyAssets, PersonalAsset
from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.routes.scheduler.model import ScheduledJob
from app.api.routes.savings_plans.model import (
    FamilySavingsPlan,
    FamilySavingsPlanContribution,
    PersonalSavingsPlan,
    PersonalSavingsPlanContribution,
)
from app.api.routes.investments.model import FamilyInvestment, PersonalInvestment, InvestmentTxn
from app.core.constants import (
    JOB_STATUS_APPLIED,
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_DELAYED,
    JOB_STATUS_FAILED,
    JOB_STATUS_SKIPPED,
    JOB_TYPE_AUTO_TRANSFER,
    JOB_TYPE_DEBT_EMI,
    JOB_TYPE_DEBT_INTEREST_INCREASE,
    JOB_TYPE_GOAL_CONTRIB,
    JOB_TYPE_ASSET_EMI,
    JOB_TYPE_ASSET_VALUE_INCREASE,
    JOB_TYPE_INSURANCE_PREMIUM,
    JOB_TYPE_INVESTMENT_CONTRIB,
    JOB_TYPE_RECURRING_EXPENSE,
    JOB_TYPE_RECURRING_INCOME,
    JOB_TYPE_SAVINGS_PLAN_CONTRIB,
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_ASSET_EMI,
    LEDGER_SOURCE_CONTRIBUTION,
    LEDGER_SOURCE_EMI,
    LEDGER_SOURCE_EXPENSE_LOG,
    LEDGER_SOURCE_INSURANCE_PREMIUM,
    LEDGER_SOURCE_INVESTMENT_CONTRIB,
    LEDGER_SOURCE_RECURRING_EXPENSE,
    LEDGER_SOURCE_RECURRING_INCOME,
    LEDGER_SOURCE_TRANSFER,
    POOL_FAMILY,
    POOL_PERSONAL,
)
from app.core.date_advance import advance_next_date
from app.core.period_key import period_key_for_date
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.transfer_pools import scope_to_pool
from app.api.routes.user.model import UserFamilyLink

logger = logging.getLogger(__name__)

SOURCE_RECURRING_INCOME = "RECURRING_INCOME"
SOURCE_FAMILY_RECURRING_INCOME = SOURCE_RECURRING_INCOME  # backward compat
SOURCE_RECURRING_EXPENSE = "RECURRING_EXPENSE"
SOURCE_FAMILY_RECURRING_EXPENSE = SOURCE_RECURRING_EXPENSE  # backward compat
SOURCE_FAMILY_EXPENSE = "FAMILY_EXPENSE"
SOURCE_PERSONAL_EXPENSE = "PERSONAL_EXPENSE"
SOURCE_FAMILY_GOAL = "FAMILY_GOAL"
SOURCE_PERSONAL_GOAL = "PERSONAL_GOAL"
SOURCE_FAMILY_SAVINGS_PLAN = "FAMILY_SAVINGS_PLAN"
SOURCE_PERSONAL_SAVINGS_PLAN = "PERSONAL_SAVINGS_PLAN"
SOURCE_TRANSFER = "TRANSFER"
SOURCE_FAMILY_ASSET = "FAMILY_ASSET"
SOURCE_PERSONAL_ASSET = "PERSONAL_ASSET"
SOURCE_FAMILY_INSURANCE = "FAMILY_INSURANCE"
SOURCE_PERSONAL_INSURANCE = "PERSONAL_INSURANCE"
SOURCE_FAMILY_INVESTMENT = "FAMILY_INVESTMENT"
SOURCE_PERSONAL_INVESTMENT = "PERSONAL_INVESTMENT"


async def apply_job(session: AsyncSession, job: ScheduledJob) -> ScheduledJob:
    """Apply a scheduled job in a single transaction. Caller commits."""
    if job.status == JOB_STATUS_APPLIED:
        return job
    if job.job_type in (JOB_TYPE_RECURRING_INCOME, JOB_TYPE_RECURRING_EXPENSE) and job.status != JOB_STATUS_AWAITING_CONFIRMATION:
        raise ValueError(f"Job cannot be applied from status {job.status}")
    try:
        if job.job_type == JOB_TYPE_RECURRING_INCOME:
            await _apply_recurring_income(session, job)
        elif job.job_type == JOB_TYPE_DEBT_EMI:
            await _apply_debt_emi(session, job)
        elif job.job_type == JOB_TYPE_RECURRING_EXPENSE:
            await _apply_recurring_expense(session, job)
        elif job.job_type == JOB_TYPE_GOAL_CONTRIB:
            logger.warning("Deprecated GOAL_CONTRIB job %s skipped", job.id)
            job.status = JOB_STATUS_SKIPPED
            return job
        elif job.job_type == JOB_TYPE_SAVINGS_PLAN_CONTRIB:
            await _apply_savings_plan_contrib(session, job)
        elif job.job_type == JOB_TYPE_AUTO_TRANSFER:
            await _apply_auto_transfer(session, job)
        elif job.job_type == JOB_TYPE_INSURANCE_PREMIUM:
            await _apply_insurance_premium(session, job)
        elif job.job_type == JOB_TYPE_DEBT_INTEREST_INCREASE:
            await _apply_debt_interest_increase(session, job)
        elif job.job_type == JOB_TYPE_INVESTMENT_CONTRIB:
            await _apply_investment_contrib(session, job)
        else:
            raise ValueError(f"Unsupported job_type: {job.job_type}")

        job.status = JOB_STATUS_APPLIED
        job.last_error = None
        await session.flush()
        return job
    except Exception as exc:
        from datetime import timedelta

        from app.core.funding_service import InsufficientFundsError

        if isinstance(exc, InsufficientFundsError):
            from app.api.routes.scheduler.model import Notification
            from app.core.constants import (
    ACTION_ACCEPT,
    ACTION_ACCEPT_WITH_SPLITS,
    ACTION_DECLINE_DELAY,
    ACTION_PAID_EXTERNALLY,
    NOTIF_STATUS_UNREAD,
)

            now = datetime.now(timezone.utc)
            job.status = JOB_STATUS_DELAYED
            job.next_retry_at = now + timedelta(days=1)
            job.last_error = str(exc)[:500]
            if job.assigned_user_id:
                session.add(
                    Notification(
                        user_id=job.assigned_user_id,
                        family_id=job.family_id,
                        type="INSUFFICIENT_FUNDS",
                        title="Payment could not be completed",
                        body=str(exc),
                        related_job_id=job.id,
                        related_entity_type=job.source_type,
                        related_entity_id=job.source_id,
                        allowed_actions={
                            "actions": [
                                ACTION_ACCEPT,
                                ACTION_ACCEPT_WITH_SPLITS,
                                ACTION_DECLINE_DELAY,
                                ACTION_PAID_EXTERNALLY,
                            ]
                        },
                        status=NOTIF_STATUS_UNREAD,
                    )
                )
            await session.flush()
            return job

        logger.exception("apply_job failed for %s: %s", job.id, exc)
        job.status = JOB_STATUS_FAILED
        job.last_error = str(exc)[:500]
        await session.flush()
        raise


async def _apply_recurring_income(session: AsyncSession, job: ScheduledJob) -> None:
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

    for split in splits:
        if split.family_id not in member_families:
            logger.warning(
                "Skipping recurring income split %s for family %s — user no longer a member",
                split.id,
                split.family_id,
            )
            continue
        log = FamilyIncomeLog(
            family_id=split.family_id,
            scope_type="FAMILY",
            logged_by=income.user_id,
            income_name=split.split_name,
            total_amount=split.amount,
            family_amount=split.amount,
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

        if split.amount > 0:
            await ledger.apply_movement(
                SavingsPoolRef(pool_type=POOL_FAMILY, family_id=split.family_id),
                split.amount,
                LEDGER_IN,
                LEDGER_SOURCE_RECURRING_INCOME,
                source_id=log.id,
                occurred_at=when,
            )

    personal_amount = income.personal_savings_amount or Decimal("0")
    personal_split_rows = list(
        (
            await session.execute(
                select(RecurringIncomePersonalSplit).where(
                    RecurringIncomePersonalSplit.income_id == income.id
                )
            )
        ).scalars().all()
    )
    if not personal_split_rows and personal_amount > 0:
        personal_split_rows = [
            type("Tmp", (), {"user_id": income.user_id, "amount": personal_amount})()
        ]

    for psplit in personal_split_rows:
        if psplit.amount <= 0:
            continue
        personal_source_id = first_log_id or job.id
        await ledger.apply_movement(
            SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=psplit.user_id),
            psplit.amount,
            LEDGER_IN,
            LEDGER_SOURCE_RECURRING_INCOME,
            source_id=personal_source_id,
            occurred_at=when,
        )
        if splits and first_log_id is not None:
            session.add(
                PersonalIncomeLog(
                    family_id=splits[0].family_id,
                    user_id=psplit.user_id,
                    logged_by=income.user_id,
                    income_name=income.income_name,
                    amount=psplit.amount,
                    income_date=when,
                    source_type="RECURRING",
                    source_id=income.id,
                    category_id=income.category_id,
                    document_id=income.document_id if income.repeat_doc_with_logs else None,
                    show_doc_to_all=income.show_docs_to_all,
                )
            )
            await session.flush()
        else:
            # Personal-only recurring (no family splits): still record a personal log
            session.add(
                PersonalIncomeLog(
                    family_id=None,
                    user_id=psplit.user_id,
                    logged_by=income.user_id,
                    income_name=income.income_name,
                    amount=psplit.amount,
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


async def _apply_debt_emi(session: AsyncSession, job: ScheduledJob) -> None:
    debt = (
        await session.execute(select(Debt).where(Debt.id == job.source_id))
    ).scalar_one_or_none()
    if debt is None or not debt.has_emi or debt.emi_next_date is None:
        raise ValueError("Debt not found or EMI inactive")

    from app.api.routes.debt.debt_service import apply_debt_emi
    await apply_debt_emi(session, debt, job)


async def _apply_recurring_expense(session: AsyncSession, job: ScheduledJob) -> None:
    if job.source_type == SOURCE_RECURRING_EXPENSE:
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
                logger.warning(
                    "Skipping recurring expense split %s for family %s — user no longer a member",
                    split.id,
                    split.family_id,
                )
                continue
            log = FamilyExpenseLog(
                family_id=split.family_id,
                scope_type="FAMILY",
                logged_by=expense.user_id,
                expense_name=split.split_name,
                amount=split.amount,
                total_amount=split.amount,
                family_amount=split.amount,
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

            if split.amount > 0:
                await ledger.apply_movement(
                    SavingsPoolRef(pool_type=POOL_FAMILY, family_id=split.family_id),
                    split.amount,
                    LEDGER_OUT,
                    LEDGER_SOURCE_RECURRING_EXPENSE,
                    source_id=log.id,
                    occurred_at=when,
                )

        personal_amount = expense.personal_savings_amount or Decimal("0")
        personal_split_rows = list(
            (
                await session.execute(
                    select(RecurringExpensePersonalSplit).where(
                        RecurringExpensePersonalSplit.expense_id == expense.id
                    )
                )
            ).scalars().all()
        )
        if not personal_split_rows and personal_amount > 0:
            personal_split_rows = [
                type("Tmp", (), {"user_id": expense.user_id, "amount": personal_amount})()
            ]

        for psplit in personal_split_rows:
            if psplit.amount <= 0:
                continue
            personal_source_id = first_log_id or job.id
            await ledger.apply_movement(
                SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=psplit.user_id),
                psplit.amount,
                LEDGER_OUT,
                LEDGER_SOURCE_RECURRING_EXPENSE,
                source_id=personal_source_id,
                occurred_at=when,
            )
            if splits and first_log_id is not None:
                session.add(
                    PersonalExpenseLog(
                        family_id=splits[0].family_id,
                        user_id=psplit.user_id,
                        logged_by=expense.user_id,
                        expense_name=expense.expense_name,
                        amount=psplit.amount,
                        expense_date=when,
                        source_type="RECURRING",
                        source_id=expense.id,
                        family_expense_log_id=first_log_id,
                        category_id=expense.category_id,
                        document_id=expense.document_id if expense.repeat_doc_with_logs else None,
                        show_doc_to_all=expense.show_docs_to_all,
                    )
                )
                await session.flush()
            else:
                # Personal-only recurring (no family splits): still record a personal log
                session.add(
                    PersonalExpenseLog(
                        family_id=None,
                        user_id=psplit.user_id,
                        logged_by=expense.user_id,
                        expense_name=expense.expense_name,
                        amount=psplit.amount,
                        expense_date=when,
                        source_type="RECURRING",
                        source_id=expense.id,
                        family_expense_log_id=None,
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
        return

    # Legacy family/personal expense rows
    is_personal = job.source_type == SOURCE_PERSONAL_EXPENSE
    model = PersonalExpense if is_personal else FamilyExpense
    expense = (
        await session.execute(select(model).where(model.id == job.source_id))
    ).scalar_one_or_none()
    if expense is None or not expense.is_recurring or expense.next_payment_date is None:
        raise ValueError("Expense not found or not recurring")

    ledger = SavingsLedgerService(session)
    user_id = getattr(expense, "user_id", None) if is_personal else None
    pool = scope_to_pool(
        expense.scope_type,
        family_id=expense.family_id,
        user_id=user_id,
    )
    when = datetime.now(timezone.utc)
    await ledger.apply_movement(
        pool,
        expense.amount,
        LEDGER_OUT,
        LEDGER_SOURCE_EXPENSE_LOG,
        source_id=job.id,
        occurred_at=when,
    )
    expense.next_payment_date = advance_next_date(
        expense.next_payment_date,
        every=expense.paid_every,
    )


async def _apply_goal_contrib(session: AsyncSession, job: ScheduledJob) -> None:
    is_personal = job.source_type == SOURCE_PERSONAL_GOAL
    model = PersonalGoal if is_personal else FamilyGoal
    goal = (
        await session.execute(select(model).where(model.id == job.source_id))
    ).scalar_one_or_none()
    if goal is None or goal.next_contribution_date is None:
        raise ValueError("Goal not found or contributions inactive")

    amount = goal.contribution_amount or job.amount
    goal.collected_amount = goal.collected_amount + amount

    ledger = SavingsLedgerService(session)
    user_id = getattr(goal, "user_id", None) if is_personal else None
    pool = scope_to_pool(
        goal.scope_type,
        family_id=goal.family_id,
        user_id=user_id,
    )
    when = datetime.now(timezone.utc)
    await ledger.apply_movement(
        pool,
        amount,
        LEDGER_OUT,
        LEDGER_SOURCE_CONTRIBUTION,
        source_id=job.id,
        occurred_at=when,
    )
    goal.next_contribution_date = advance_next_date(
        goal.next_contribution_date,
        every=goal.contribution_every,
    )


async def _apply_savings_plan_contrib(session: AsyncSession, job: ScheduledJob) -> None:
    is_personal = job.source_type == SOURCE_PERSONAL_SAVINGS_PLAN
    model = PersonalSavingsPlan if is_personal else FamilySavingsPlan
    plan = (
        await session.execute(select(model).where(model.id == job.source_id))
    ).scalar_one_or_none()
    if plan is None or plan.next_contribution_date is None:
        raise ValueError("Savings plan not found or contributions inactive")

    amount = plan.contribution_amount or job.amount
    plan.accumulated_amount = plan.accumulated_amount + amount

    from app.core.funding_service import FundingService
    fs = FundingService(session)
    user_id = getattr(plan, "user_id", None) if is_personal else None
    pool = scope_to_pool(
        plan.scope_type,
        family_id=plan.family_id,
        user_id=user_id,
    )
    when = datetime.now(timezone.utc)
    
    from app.core.funding_service import SplitLine

    split_lines = None
    if job.meta and isinstance(job.meta, dict) and "split_lines" in job.meta:
        split_lines = [
            SplitLine(pool_type=s["poolType"], family_id=s.get("familyId"), amount=Decimal(str(s["amount"])))
            for s in job.meta["split_lines"]
        ]
    if split_lines is None:
        plan_lines = await fs.load_split_plan(job.source_type, job.source_id)
        if plan_lines:
            split_lines = [
                SplitLine(pool_type=sl.pool_type, family_id=sl.family_id, amount=sl.amount)
                for sl in plan_lines
            ]

    if split_lines:
        await fs.execute_debit(
            split_lines,
            amount,
            ledger_source_type=LEDGER_SOURCE_CONTRIBUTION,
            entity_type=job.source_type,
            entity_id=job.source_id,
            description=f"Savings plan contrib — {plan.plan_name}",
            occurred_at=when,
        )
    else:
        await fs.execute_debit_adhoc(
            pool,
            amount,
            ledger_source_type=LEDGER_SOURCE_CONTRIBUTION,
            entity_type=job.source_type,
            entity_id=job.source_id,
            description=f"Savings plan contrib — {plan.plan_name}",
            occurred_at=when,
        )
    if is_personal:
        session.add(
            PersonalSavingsPlanContribution(
                family_id=plan.family_id,
                scope_type=plan.scope_type,
                plan_id=plan.id,
                user_id=plan.user_id,
                amount=amount,
                direction="IN",
                contribution_date=when,
                source_type="SCHEDULED",
                source_id=job.id,
            )
        )
    else:
        session.add(
            FamilySavingsPlanContribution(
                family_id=plan.family_id,
                scope_type=plan.scope_type,
                plan_id=plan.id,
                contributed_by=job.assigned_user_id,
                amount=amount,
                direction="IN",
                contribution_date=when,
                source_type="SCHEDULED",
                source_id=job.id,
            )
        )
    plan.next_contribution_date = advance_next_date(
        plan.next_contribution_date,
        every=plan.contribution_every,
    )
    from app.scheduler.savings_plan_cron import (
        check_completion,
        create_or_replace_next_contrib_job,
    )

    completed = await check_completion(session, plan, job.source_type)
    if not completed:
        await create_or_replace_next_contrib_job(session, plan, job.source_type)


async def _apply_auto_transfer(session: AsyncSession, job: ScheduledJob) -> None:
    transfer = (
        await session.execute(select(Transfer).where(Transfer.id == job.source_id))
    ).scalar_one_or_none()
    if transfer is None:
        raise ValueError("Transfer not found")

    from app.api.routes.transfer.transfer_service import TransferService

    svc = TransferService(session)
    await svc.execute_transfer_run(transfer)


async def _apply_insurance_premium(session: AsyncSession, job: ScheduledJob) -> None:
    is_personal = job.source_type == SOURCE_PERSONAL_INSURANCE
    model = PersonalInsurance if is_personal else FamilyInsurance
    insurance = (
        await session.execute(select(model).where(model.id == job.source_id))
    ).scalar_one_or_none()
    if insurance is None or insurance.next_premium_date is None:
        raise ValueError("Insurance not found or premium inactive")

    amount = insurance.premium_amount or job.amount
    
    from app.core.funding_service import FundingService
    fs = FundingService(session)
    user_id = getattr(insurance, "user_id", None) if is_personal else None
    pool = scope_to_pool(
        insurance.scope_type,
        family_id=insurance.family_id,
        user_id=user_id,
    )
    when = datetime.now(timezone.utc)
    
    split_lines = None
    if job.meta and isinstance(job.meta, dict) and "split_lines" in job.meta:
        from app.core.funding_service import SplitLine
        split_lines = [
            SplitLine(pool_type=s["poolType"], family_id=s.get("familyId"), amount=Decimal(str(s["amount"])))
            for s in job.meta["split_lines"]
        ]

    if split_lines:
        await fs.execute_debit(
            split_lines,
            amount,
            ledger_source_type=LEDGER_SOURCE_INSURANCE_PREMIUM,
            entity_type=job.source_type,
            entity_id=job.source_id,
            description=f"Insurance premium — {insurance.insurance_name}",
            occurred_at=when,
        )
    else:
        await fs.execute_debit_adhoc(
            pool,
            amount,
            ledger_source_type=LEDGER_SOURCE_INSURANCE_PREMIUM,
            entity_type=job.source_type,
            entity_id=job.source_id,
            description=f"Insurance premium — {insurance.insurance_name}",
            occurred_at=when,
        )
    insurance.next_premium_date = advance_next_date(
        insurance.next_premium_date,
        every=insurance.premium_every,
    )


async def _apply_investment_contrib(session: AsyncSession, job: ScheduledJob) -> None:
    is_personal = job.source_type == SOURCE_PERSONAL_INVESTMENT
    model = PersonalInvestment if is_personal else FamilyInvestment
    inv = (
        await session.execute(select(model).where(model.id == job.source_id))
    ).scalar_one_or_none()
    if inv is None or not inv.has_recurring or inv.next_contribution_date is None:
        raise ValueError("Investment not found or recurring contribution inactive")

    amount = inv.contribution_amount or job.amount

    from app.core.funding_service import FundingService

    fs = FundingService(session)
    pool = scope_to_pool(
        "PERSONAL" if is_personal else "FAMILY",
        family_id=inv.family_id,
        user_id=getattr(inv, "user_id", None) if is_personal else None,
    )
    when = datetime.now(timezone.utc)

    split_lines = None
    if job.meta and isinstance(job.meta, dict) and "split_lines" in job.meta:
        from app.core.funding_service import SplitLine

        split_lines = [
            SplitLine(pool_type=s["poolType"], family_id=s.get("familyId"), amount=Decimal(str(s["amount"])))
            for s in job.meta["split_lines"]
        ]
    if split_lines is None:
        plan_lines = await fs.load_split_plan(job.source_type, job.source_id)
        if plan_lines:
            from app.core.funding_service import SplitLine

            split_lines = [
                SplitLine(pool_type=sl.pool_type, family_id=sl.family_id, amount=sl.amount)
                for sl in plan_lines
            ]

    if split_lines:
        await fs.execute_debit(
            split_lines,
            amount,
            ledger_source_type=LEDGER_SOURCE_INVESTMENT_CONTRIB,
            entity_type=job.source_type,
            entity_id=job.source_id,
            job_id=job.id,
            description=f"Contribution — {inv.investment_name}",
            occurred_at=when,
        )
    else:
        await fs.execute_debit_adhoc(
            pool,
            amount,
            ledger_source_type=LEDGER_SOURCE_INVESTMENT_CONTRIB,
            entity_type=job.source_type,
            entity_id=job.source_id,
            job_id=job.id,
            description=f"Contribution — {inv.investment_name}",
            occurred_at=when,
        )

    inv.invested_amount = (inv.invested_amount or Decimal("0")) + amount
    inv.current_value = (inv.current_value or Decimal("0")) + amount

    session.add(
        InvestmentTxn(
            investment_scope="PERSONAL" if is_personal else "FAMILY",
            investment_id=inv.id,
            txn_type="CONTRIBUTION",
            amount=amount,
            direction="OUT",
            occurred_at=when,
            source_type="SCHEDULED",
            job_id=job.id,
        )
    )

    inv.next_contribution_date = advance_next_date(
        inv.next_contribution_date, every=inv.contribution_every or "MONTHLY"
    )

    from app.scheduler.investment_cron import create_or_replace_next_contrib_job

    await create_or_replace_next_contrib_job(session, inv, job.source_type)


async def _apply_debt_interest_increase(session: AsyncSession, job: ScheduledJob) -> None:
    debt = (
        await session.execute(select(Debt).where(Debt.id == job.source_id))
    ).scalar_one_or_none()
    if debt is None or not debt.has_interest or debt.next_interest_increase_date is None:
        raise ValueError("Debt not found or interest increase inactive")

    pct = debt.interest_increase_percentage or 0
    if debt.interest_type == "FLOATING" and debt.interest_rate is not None:
        debt.interest_rate = debt.interest_rate * (1 + pct / 100)
        if debt.has_emi and debt.emi_amount is not None and debt.tenure_months:
            from app.core.interest_math import compute_emi

            debt.emi_amount = compute_emi(
                debt.remaining_amount,
                debt.interest_rate,
                debt.tenure_months,
                debt.interest_type,
                debt.compounding_frequency or "MONTHLY",
            )
    debt.next_interest_increase_date = advance_next_date(
        debt.next_interest_increase_date,
        every=debt.interest_increase_every,
    )



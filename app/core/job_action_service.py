"""Shared job/notification action state machine (Family System V2)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.assets.model import FamilyAssets, PersonalAsset
from app.api.routes.debt.model import Debt
from app.api.routes.expense.model import FamilyExpense, PersonalExpense
from app.api.routes.family_expense.model import RecurringExpense
from app.api.routes.family_income.model import RecurringIncome
from app.api.routes.goals.model import FamilyGoal, PersonalGoal
from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.routes.savings_plans.model import FamilySavingsPlan, PersonalSavingsPlan
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.api.routes.transfer.model import Transfer
from app.config import scheduler_settings
from app.core.constants import (
    ACTION_ACCEPT,
    ACTION_DECLINE_DELAY,
    ACTION_DISMISS,
    ACTION_REMOVE_RECURRING,
    ACTION_REMOVE_SOURCE,
    ACTION_SKIP_DEFAULT,
    ACTION_SKIP_INCREASE,
    ACTION_SKIP_PERIOD,
    DEFAULT_BUCKET_REASON_BOUNCED,
    DEFAULT_BUCKET_REASON_SKIPPED_TO_DEFAULT,
    JOB_STATUS_APPLIED,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_DELAYED,
    JOB_STATUS_SKIPPED,
    JOB_TYPE_ASSET_EMI,
    JOB_TYPE_ASSET_VALUE_INCREASE,
    JOB_TYPE_DEBT_EMI,
    JOB_TYPE_DEBT_INTEREST_INCREASE,
    JOB_TYPE_GOAL_CONTRIB,
    JOB_TYPE_INSURANCE_PREMIUM,
    JOB_TYPE_RECURRING_EXPENSE,
    JOB_TYPE_RECURRING_INCOME,
    JOB_TYPE_SAVINGS_PLAN_CONTRIB,
    NOTIF_STATUS_ACTIONED,
    NOTIF_STATUS_DISMISSED,
    SOURCE_DEBT,
    ACTION_PAID_EXTERNALLY,
    ACTION_ACCEPT_WITH_SPLITS,
    ACTION_ADJUST_AMOUNT,
)
from app.core.date_advance import advance_next_date
from app.core.emi_recompute import recompute_plan_contribution
from app.scheduler.jobs import (
    SOURCE_FAMILY_ASSET,
    SOURCE_FAMILY_EXPENSE,
    SOURCE_FAMILY_GOAL,
    SOURCE_FAMILY_INSURANCE,
    SOURCE_RECURRING_EXPENSE,
    SOURCE_RECURRING_INCOME,
    SOURCE_FAMILY_RECURRING_EXPENSE,
    SOURCE_FAMILY_RECURRING_INCOME,
    SOURCE_FAMILY_SAVINGS_PLAN,
    SOURCE_PERSONAL_ASSET,
    SOURCE_PERSONAL_EXPENSE,
    SOURCE_PERSONAL_GOAL,
    SOURCE_PERSONAL_INSURANCE,
    SOURCE_PERSONAL_SAVINGS_PLAN,
    SOURCE_TRANSFER,
    apply_job,
)


def _allowed_actions(notification: Notification | None) -> list[str]:
    if notification is None:
        return []
    allowed = notification.allowed_actions
    if isinstance(allowed, dict):
        return list(allowed.get("actions", []))
    if isinstance(allowed, list):
        return allowed
    return []


class JobActionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._handlers = {
            ACTION_ACCEPT: self._handle_accept,
            ACTION_DECLINE_DELAY: self._handle_decline_delay,
            ACTION_SKIP_PERIOD: self._handle_skip_period,
            ACTION_SKIP_DEFAULT: self._handle_skip_default_or_increase,
            ACTION_SKIP_INCREASE: self._handle_skip_default_or_increase,
            ACTION_REMOVE_SOURCE: self._handle_remove,
            ACTION_REMOVE_RECURRING: self._handle_remove,
            ACTION_DISMISS: self._handle_dismiss,
            ACTION_PAID_EXTERNALLY: self._handle_paid_externally,
            ACTION_ACCEPT_WITH_SPLITS: self._handle_accept_with_splits,
            ACTION_ADJUST_AMOUNT: self._handle_adjust_amount,
        }

    async def apply_action(
        self,
        job: ScheduledJob,
        notification: Notification | None,
        action: str,
        *,
        delay_days: int | None = None,
        actor_user_id: UUID,
        payload: dict | None = None,
    ) -> ScheduledJob:
        if notification and notification.user_id != actor_user_id:
            raise PermissionError("Not the notification recipient")

        # Idempotent retries: already-applied jobs are a no-op
        if job.status == JOB_STATUS_APPLIED and action in (
            ACTION_ACCEPT,
            ACTION_PAID_EXTERNALLY,
            ACTION_ACCEPT_WITH_SPLITS,
            ACTION_ADJUST_AMOUNT,
        ):
            return job

        allowed = _allowed_actions(notification)
        if notification and allowed and action not in allowed:
            raise ValueError(f"Action {action} not allowed")

        now = datetime.now(timezone.utc)
        
        handler = self._handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")
            
        await handler(job, notification, action, now, delay_days=delay_days, payload=payload)

        await self.session.flush()
        return job

    async def _handle_accept(self, job, notification, action, now, **kwargs):
        await apply_job(self.session, job)
        self._mark_notification(notification, action, now)

    async def _handle_decline_delay(self, job, notification, action, now, delay_days, **kwargs):
        days = delay_days or scheduler_settings.JOB_DEFAULT_DELAY_DAYS
        job.status = JOB_STATUS_DELAYED
        job.delay_days = days
        job.attempt_count += 1
        job.next_retry_at = now + timedelta(days=days)
        if job.attempt_count >= scheduler_settings.JOB_MAX_RETRIES:
            job.status = JOB_STATUS_SKIPPED
            if job.job_type == JOB_TYPE_DEBT_EMI:
                await self._record_debt_default(
                    job, reason=DEFAULT_BUCKET_REASON_BOUNCED
                )
        self._mark_notification(notification, action, now)

    async def _handle_skip_period(self, job, notification, action, now, **kwargs):
        job.status = JOB_STATUS_SKIPPED
        if job.job_type == JOB_TYPE_DEBT_EMI:
            await self._record_debt_default(
                job, reason=DEFAULT_BUCKET_REASON_SKIPPED_TO_DEFAULT
            )
            await self._advance_emi_source(job)
        else:
            await self._advance_source_after_skip(job)
        self._mark_notification(notification, action, now)

    async def _handle_skip_default_or_increase(self, job, notification, action, now, **kwargs):
        job.status = JOB_STATUS_SKIPPED
        if job.job_type == JOB_TYPE_DEBT_EMI:
            if action == ACTION_SKIP_DEFAULT:
                await self._record_debt_default(
                    job, reason=DEFAULT_BUCKET_REASON_SKIPPED_TO_DEFAULT
                )
            await self._advance_emi_source(job)
            if action == ACTION_SKIP_INCREASE:
                await self._recompute_emi_source(job)
        elif job.job_type == JOB_TYPE_SAVINGS_PLAN_CONTRIB:
            if action == ACTION_SKIP_DEFAULT:
                await self._record_savings_plan_default(
                    job, reason=DEFAULT_BUCKET_REASON_SKIPPED_TO_DEFAULT
                )
            await self._advance_emi_source(job)
            if action == ACTION_SKIP_INCREASE:
                await self._recompute_emi_source(job)
        else:
            await self._advance_emi_source(job)
            if action == ACTION_SKIP_INCREASE:
                await self._recompute_emi_source(job)
        self._mark_notification(notification, action, now)

    async def _handle_remove(self, job, notification, action, now, **kwargs):
        job.status = JOB_STATUS_CANCELLED
        await self._cancel_source(job)
        self._mark_notification(notification, action, now)

    async def _handle_dismiss(self, job, notification, action, now, **kwargs):
        if notification:
            notification.status = NOTIF_STATUS_DISMISSED
            notification.action_taken = action
            notification.actioned_at = now

    async def _handle_paid_externally(self, job, notification, action, now, **kwargs):
        if job.job_type == JOB_TYPE_RECURRING_EXPENSE:
            from app.core.job_actions.recurring_expense import apply_paid_externally
            await apply_paid_externally(self.session, job)
        elif job.job_type == JOB_TYPE_DEBT_EMI:
            await self._apply_debt_emi_action(
                job, paid_externally=True, skip_funding=False
            )
            job.status = JOB_STATUS_APPLIED
        else:
            from app.core.funding_service import FundingService
            fs = FundingService(self.session)
            await fs.execute_paid_externally(
                entity_type=job.source_type,
                entity_id=job.source_id,
                amount=job.amount,
                job_id=job.id,
                description="Paid externally",
            )
            job.status = JOB_STATUS_SKIPPED
            await self._advance_source_after_skip(job)
        self._mark_notification(notification, action, now)

    async def _handle_accept_with_splits(self, job, notification, action, now, payload, **kwargs):
        split_lines = (payload or {}).get("splitLines") or (payload or {}).get("split_lines")
        if not split_lines:
            raise ValueError("ACCEPT_WITH_SPLITS requires payload.splitLines")
        if job.job_type == JOB_TYPE_RECURRING_EXPENSE:
            from app.core.job_actions.recurring_expense import apply_expense_with_sources
            await apply_expense_with_sources(
                self.session, job, job.amount, split_lines
            )
        elif job.job_type == JOB_TYPE_DEBT_EMI:
            from decimal import Decimal as D
            from app.core.funding_service import FundingService, SplitLine
            from app.core.constants import LEDGER_SOURCE_DEBT_EMI

            fs = FundingService(self.session)
            lines = [
                SplitLine(
                    pool_type=ln["poolType"] if "poolType" in ln else ln["pool_type"],
                    amount=D(str(ln["amount"])),
                    family_id=ln.get("familyId") or ln.get("family_id"),
                    user_id=ln.get("userId") or ln.get("user_id"),
                )
                for ln in split_lines
            ]
            await fs.execute_debit(
                lines,
                job.amount,
                ledger_source_type=LEDGER_SOURCE_DEBT_EMI,
                entity_type=SOURCE_DEBT,
                entity_id=job.source_id,
                job_id=job.id,
                description=f"Split-accepted EMI for job {job.id}",
            )
            await self._apply_debt_emi_action(
                job,
                paid_externally=False,
                skip_funding=True,
                allocations=lines,
            )
            job.status = JOB_STATUS_APPLIED
        else:
            from decimal import Decimal as D
            from app.core.funding_service import FundingService, SplitLine
            from app.core.constants import LEDGER_SOURCE_EMI

            fs = FundingService(self.session)
            lines = [
                SplitLine(
                    pool_type=ln["poolType"] if "poolType" in ln else ln["pool_type"],
                    amount=D(str(ln["amount"])),
                    family_id=ln.get("familyId") or ln.get("family_id"),
                    user_id=ln.get("userId") or ln.get("user_id"),
                )
                for ln in split_lines
            ]
            await fs.execute_debit(
                lines,
                job.amount,
                ledger_source_type=LEDGER_SOURCE_EMI,
                entity_type=job.source_type,
                entity_id=job.source_id,
                job_id=job.id,
                description=f"Split-accepted payment for job {job.id}",
            )
            job.status = JOB_STATUS_APPLIED
            await self._advance_source_after_skip(job)
        self._mark_notification(notification, action, now)

    async def _handle_adjust_amount(self, job, notification, action, now, payload, **kwargs):
        payload = payload or {}
        if job.job_type == JOB_TYPE_RECURRING_INCOME:
            from app.core.job_actions.recurring_income import apply_adjusted_income
            await apply_adjusted_income(self.session, job, payload)
        elif job.job_type == JOB_TYPE_RECURRING_EXPENSE:
            from app.core.job_actions.recurring_expense import apply_adjusted_expense
            await apply_adjusted_expense(self.session, job, payload)
        elif job.job_type == JOB_TYPE_DEBT_EMI and job.source_type == SOURCE_DEBT:
            await self._handle_debt_adjust_amount(job, payload)
        else:
            new_amount_raw = payload.get("newAmount") or payload.get("new_amount")
            if new_amount_raw is None:
                raise ValueError("ADJUST_AMOUNT requires payload.newAmount")
            from decimal import Decimal as D

            new_amount = D(str(new_amount_raw))
            original_amount = job.amount
            job.amount = new_amount
            await apply_job(self.session, job)
            job.amount = original_amount
        self._mark_notification(notification, action, now)

    async def _handle_debt_adjust_amount(self, job: ScheduledJob, payload: dict) -> None:
        """Apply adjusted EMI amount with under/overpayment recalculation policies."""
        from decimal import Decimal as D

        from app.api.routes.debt.debt_service import (
            apply_debt_emi,
            resolve_debt,
        )
        from app.core.interest_math import compute_emi, recompute_after_part_payment
        from app.scheduler.debt_cron import create_or_replace_next_debt_job

        new_amount_raw = payload.get("newAmount") or payload.get("new_amount")
        if new_amount_raw is None:
            raise ValueError("ADJUST_AMOUNT requires payload.newAmount")
        new_amount = D(str(new_amount_raw))
        if new_amount <= 0:
            raise ValueError("Adjusted amount must be positive")

        debt = await resolve_debt(self.session, job.source_id)
        if debt is None:
            raise ValueError("Debt not found for adjusted EMI")

        scheduled = job.amount or debt.emi_amount or D("0")
        under_policy = (
            payload.get("underpaymentPolicy")
            or payload.get("underpayment_policy")
            or "INCREASE_EMI_KEEP_TENURE"
        )
        over_policy = (
            payload.get("overpaymentPolicy")
            or payload.get("overpayment_policy")
            or "REDUCE_NEXT_EMI"
        )

        original_amount = job.amount
        job.amount = new_amount
        await apply_debt_emi(
            self.session,
            debt,
            job,
            underpayment_policy=under_policy if new_amount < scheduled else None,
            overpayment_policy=over_policy if new_amount > scheduled else None,
        )
        job.amount = original_amount
        job.status = JOB_STATUS_APPLIED

        diff = new_amount - scheduled
        remaining_periods = debt.tenure_months or 12
        rate = debt.interest_rate or 0.0
        itype = debt.interest_type or "NONE"
        real_remaining = debt.remaining_amount or D("0")

        if diff < 0:
            # Underpayment: recalculate remaining schedule
            if under_policy == "EXTEND_TENURE_KEEP_EMI":
                result = recompute_after_part_payment(
                    real_remaining,
                    debt.emi_amount or scheduled,
                    rate,
                    itype,
                    remaining_periods,
                    "REDUCE_TENURE",
                )
                debt.tenure_months = result["new_periods"]
            else:
                # INCREASE_EMI_KEEP_TENURE
                if remaining_periods > 0:
                    new_emi = compute_emi(real_remaining, rate, remaining_periods, itype)
                    debt.emi_amount = new_emi
        elif diff > 0:
            if over_policy == "PART_PAYMENT":
                # Excess already applied to principal via apply_debt_emi using job.amount;
                # caller should open part-payment UI for any remaining policy choice.
                pass
            else:
                # REDUCE_NEXT_EMI — reduce the stored EMI by the overpaid difference once
                current = debt.emi_amount or scheduled
                reduced = max(D("0.01"), current - diff)
                debt.emi_amount = reduced

        if debt.status == "ACTIVE" and debt.has_emi and debt.emi_next_date:
            await create_or_replace_next_debt_job(
                self.session, debt, SOURCE_DEBT
            )

    def _mark_notification(self, notification, action, now):
        if notification:
            notification.status = NOTIF_STATUS_ACTIONED
            notification.action_taken = action
            notification.actioned_at = now

    async def _cancel_source(self, job: ScheduledJob) -> None:
        st = job.source_type
        sid = job.source_id

        if st in (SOURCE_RECURRING_INCOME, SOURCE_FAMILY_RECURRING_INCOME):
            income = (
                await self.session.execute(
                    select(RecurringIncome).where(RecurringIncome.id == sid)
                )
            ).scalar_one_or_none()
            if income:
                income.next_receiving_date = None
                from app.scheduler.income_cron import cancel_pending_income_jobs

                await cancel_pending_income_jobs(self.session, income.id)
            return

        if st in (SOURCE_RECURRING_EXPENSE, SOURCE_FAMILY_RECURRING_EXPENSE):
            expense = (
                await self.session.execute(
                    select(RecurringExpense).where(RecurringExpense.id == sid)
                )
            ).scalar_one_or_none()
            if expense:
                expense.next_payment_date = None
                from app.scheduler.expense_cron import cancel_pending_expense_jobs

                await cancel_pending_expense_jobs(self.session, expense.id)
            return

        if st == SOURCE_DEBT:
            debt = (
                await self.session.execute(select(Debt).where(Debt.id == sid))
            ).scalar_one_or_none()
            if debt:
                # REMOVE_RECURRING: stop EMI schedule only — do not cancel the debt itself
                debt.has_emi = False
                debt.emi_next_date = None
                from app.scheduler.debt_cron import cancel_pending_debt_jobs

                await cancel_pending_debt_jobs(self.session, debt.id, SOURCE_DEBT)
            return

        if st in (SOURCE_FAMILY_EXPENSE, SOURCE_PERSONAL_EXPENSE):
            model = PersonalExpense if st == SOURCE_PERSONAL_EXPENSE else FamilyExpense
            expense = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if expense:
                expense.is_recurring = False
                expense.next_payment_date = None
            return

        if st in (SOURCE_FAMILY_GOAL, SOURCE_PERSONAL_GOAL):
            model = PersonalGoal if st == SOURCE_PERSONAL_GOAL else FamilyGoal
            goal = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if goal:
                goal.status = "CANCELLED"
            return

        if st in (SOURCE_FAMILY_SAVINGS_PLAN, SOURCE_PERSONAL_SAVINGS_PLAN):
            model = PersonalSavingsPlan if st == SOURCE_PERSONAL_SAVINGS_PLAN else FamilySavingsPlan
            plan = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if plan:
                plan.auto_deduct = False
                plan.next_contribution_date = None
                plan.status = "CANCELLED"
            return

        if st in (SOURCE_FAMILY_ASSET, SOURCE_PERSONAL_ASSET):
            model = PersonalAsset if st == SOURCE_PERSONAL_ASSET else FamilyAssets
            asset = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if asset:
                if job.job_type == JOB_TYPE_ASSET_VALUE_INCREASE:
                    asset.is_increasing = False
                    asset.next_increase_date = None
                else:
                    asset.has_emi = False
                    asset.emi_next_date = None
            return

        if st in (SOURCE_FAMILY_INSURANCE, SOURCE_PERSONAL_INSURANCE):
            model = PersonalInsurance if st == SOURCE_PERSONAL_INSURANCE else FamilyInsurance
            ins = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if ins:
                ins.status = "CANCELLED"
                ins.next_premium_date = None
            return

        if st == SOURCE_TRANSFER:
            transfer = (
                await self.session.execute(select(Transfer).where(Transfer.id == sid))
            ).scalar_one_or_none()
            if transfer:
                transfer.is_recurring = False
            return

    async def _advance_source_after_skip(self, job: ScheduledJob) -> None:
        st = job.source_type
        sid = job.source_id

        if st in (SOURCE_RECURRING_INCOME, SOURCE_FAMILY_RECURRING_INCOME):
            income = (
                await self.session.execute(
                    select(RecurringIncome).where(RecurringIncome.id == sid)
                )
            ).scalar_one_or_none()
            if income and income.next_receiving_date:
                income.next_receiving_date = advance_next_date(
                    income.next_receiving_date,
                    every=income.received_every,
                    interval_days=income.repeat_interval_days,
                    interval_months=income.repeat_interval_months,
                    interval_years=income.repeat_interval_years,
                )
                from app.scheduler.income_cron import create_or_replace_next_job

                await create_or_replace_next_job(self.session, income)
            return

        if st in (SOURCE_RECURRING_EXPENSE, SOURCE_FAMILY_RECURRING_EXPENSE):
            expense = (
                await self.session.execute(
                    select(RecurringExpense).where(RecurringExpense.id == sid)
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

                await create_or_replace_next_job(self.session, expense)
            return

        if st in (SOURCE_FAMILY_EXPENSE, SOURCE_PERSONAL_EXPENSE):
            model = PersonalExpense if st == SOURCE_PERSONAL_EXPENSE else FamilyExpense
            expense = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if expense and expense.next_payment_date:
                expense.next_payment_date = advance_next_date(
                    expense.next_payment_date, every=expense.paid_every
                )
            return

        if st in (SOURCE_FAMILY_SAVINGS_PLAN, SOURCE_PERSONAL_SAVINGS_PLAN):
            model = PersonalSavingsPlan if st == SOURCE_PERSONAL_SAVINGS_PLAN else FamilySavingsPlan
            plan = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if plan and plan.next_contribution_date:
                plan.next_contribution_date = advance_next_date(
                    plan.next_contribution_date, every=plan.contribution_every
                )
            return

        if st in (SOURCE_FAMILY_ASSET, SOURCE_PERSONAL_ASSET):
            model = PersonalAsset if st == SOURCE_PERSONAL_ASSET else FamilyAssets
            asset = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if asset:
                if job.job_type == JOB_TYPE_ASSET_VALUE_INCREASE and asset.next_increase_date:
                    asset.next_increase_date = advance_next_date(
                        asset.next_increase_date, every=asset.increase_every
                    )
                elif asset.emi_next_date:
                    asset.emi_next_date = advance_next_date(
                        asset.emi_next_date, every=asset.emi_every
                    )
            return

        if st in (SOURCE_FAMILY_INSURANCE, SOURCE_PERSONAL_INSURANCE):
            model = PersonalInsurance if st == SOURCE_PERSONAL_INSURANCE else FamilyInsurance
            ins = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if ins and ins.next_premium_date:
                ins.next_premium_date = advance_next_date(
                    ins.next_premium_date, every=ins.premium_every
                )
            return

        if st == SOURCE_DEBT:
            debt = await self._load_debt(sid)
            if debt is None:
                return
            if job.job_type == JOB_TYPE_DEBT_EMI and debt.emi_next_date:
                days = getattr(debt, "emi_interval_days", None)
                months = getattr(debt, "emi_interval_months", None)
                years = getattr(debt, "emi_interval_years", None)
                if days or months or years:
                    debt.emi_next_date = advance_next_date(
                        debt.emi_next_date,
                        interval_days=days,
                        interval_months=months,
                        interval_years=years,
                    )
                else:
                    debt.emi_next_date = advance_next_date(
                        debt.emi_next_date, every=debt.emi_every or "MONTHLY"
                    )
                from app.scheduler.debt_cron import create_or_replace_next_debt_job

                await create_or_replace_next_debt_job(self.session, debt, SOURCE_DEBT)
            elif debt.next_interest_increase_date:
                debt.next_interest_increase_date = advance_next_date(
                    debt.next_interest_increase_date,
                    every=debt.interest_increase_every,
                )
            return

    async def _load_debt(self, source_id: UUID) -> Debt | None:
        return (
            await self.session.execute(select(Debt).where(Debt.id == source_id))
        ).scalar_one_or_none()

    async def _apply_debt_emi_action(
        self,
        job: ScheduledJob,
        *,
        paid_externally: bool = False,
        skip_funding: bool = False,
        allocations=None,
    ) -> None:
        from app.api.routes.debt.debt_service import apply_debt_emi

        debt = await self._load_debt(job.source_id)
        if debt is None or not debt.has_emi:
            raise ValueError("Debt not found or EMI inactive")
        await apply_debt_emi(
            self.session,
            debt,
            job,
            skip_funding=skip_funding,
            paid_externally=paid_externally,
            allocations=allocations,
        )

    async def _advance_emi_source(self, job: ScheduledJob) -> None:
        """Advance the next due date for a plan/goal/debt-EMI job by one period."""
        st = job.source_type
        sid = job.source_id

        if st in (SOURCE_FAMILY_SAVINGS_PLAN, SOURCE_PERSONAL_SAVINGS_PLAN):
            model = PersonalSavingsPlan if st == SOURCE_PERSONAL_SAVINGS_PLAN else FamilySavingsPlan
            plan = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if plan and plan.next_contribution_date:
                plan.next_contribution_date = advance_next_date(
                    plan.next_contribution_date, every=plan.contribution_every
                )
            return

        if st == SOURCE_DEBT:
            debt = await self._load_debt(sid)
            if debt and debt.emi_next_date:
                days = getattr(debt, "emi_interval_days", None)
                months = getattr(debt, "emi_interval_months", None)
                years = getattr(debt, "emi_interval_years", None)
                if days or months or years:
                    debt.emi_next_date = advance_next_date(
                        debt.emi_next_date,
                        interval_days=days,
                        interval_months=months,
                        interval_years=years,
                    )
                else:
                    debt.emi_next_date = advance_next_date(
                        debt.emi_next_date, every=debt.emi_every or "MONTHLY"
                    )
                from app.scheduler.debt_cron import create_or_replace_next_debt_job

                await create_or_replace_next_debt_job(self.session, debt, SOURCE_DEBT)
            return

    async def _record_debt_default(
        self, job: ScheduledJob, *, reason: str = DEFAULT_BUCKET_REASON_BOUNCED
    ) -> None:
        """Record a missed EMI in the default bucket and reschedule the next job."""
        from app.core.default_bucket_service import DefaultBucketService
        from app.core.period_key import period_key_for_date
        from app.scheduler.debt_cron import create_or_replace_next_debt_job

        st = job.source_type
        if st != SOURCE_DEBT:
            return

        debt = (
            await self.session.execute(select(Debt).where(Debt.id == job.source_id))
        ).scalar_one_or_none()
        if debt is None or not getattr(debt, "allow_auto_default", True):
            return

        period = job.period_key or period_key_for_date(
            job.scheduled_for or datetime.now(timezone.utc),
            every=debt.emi_every or "MONTHLY",
        )
        bucket = DefaultBucketService(self.session)
        await bucket.add_entry(
            entity_type=st,
            entity_id=debt.id,
            period_key=period,
            amount=job.amount,
            fine_amount=debt.bounce_fine_amount or Decimal("0"),
            reason=reason,
            family_id=job.family_id,
            user_id=debt.owner_user_id,
        )
        await create_or_replace_next_debt_job(self.session, debt, st)

    async def _record_savings_plan_default(
        self, job: ScheduledJob, *, reason: str = DEFAULT_BUCKET_REASON_BOUNCED
    ) -> None:
        """Record a missed savings contribution in the default bucket."""
        from app.core.default_bucket_service import DefaultBucketService
        from app.core.period_key import period_key_for_date
        from app.scheduler.savings_plan_cron import create_or_replace_next_contrib_job

        st = job.source_type
        if st not in (SOURCE_FAMILY_SAVINGS_PLAN, SOURCE_PERSONAL_SAVINGS_PLAN):
            return

        is_personal = st == SOURCE_PERSONAL_SAVINGS_PLAN
        model = PersonalSavingsPlan if is_personal else FamilySavingsPlan
        plan = (
            await self.session.execute(select(model).where(model.id == job.source_id))
        ).scalar_one_or_none()
        if plan is None:
            return

        period = job.period_key or period_key_for_date(
            job.scheduled_for or datetime.now(timezone.utc),
            every=plan.contribution_every or "MONTHLY",
        )
        bucket = DefaultBucketService(self.session)
        await bucket.add_entry(
            entity_type=st,
            entity_id=plan.id,
            period_key=period,
            amount=job.amount,
            fine_amount=getattr(plan, "skip_fine_amount", None) or Decimal("0"),
            reason=reason,
            family_id=plan.family_id if not is_personal else None,
            user_id=getattr(plan, "user_id", None) if is_personal else None,
        )
        await create_or_replace_next_contrib_job(self.session, plan, st)

    async def _recompute_emi_source(self, job: ScheduledJob) -> None:
        """Recompute per-period amount so the target is still met after a skip."""
        st = job.source_type
        sid = job.source_id

        if st in (SOURCE_FAMILY_SAVINGS_PLAN, SOURCE_PERSONAL_SAVINGS_PLAN):
            model = PersonalSavingsPlan if st == SOURCE_PERSONAL_SAVINGS_PLAN else FamilySavingsPlan
            plan = (
                await self.session.execute(select(model).where(model.id == sid))
            ).scalar_one_or_none()
            if plan:
                plan.contribution_amount = recompute_plan_contribution(plan)
            return

        if st == SOURCE_DEBT:
            from app.core.interest_math import recompute_after_skip

            debt = (
                await self.session.execute(select(Debt).where(Debt.id == sid))
            ).scalar_one_or_none()
            if debt and debt.emi_amount is not None:
                remaining = debt.remaining_amount
                periods = debt.tenure_months or 12
                new_emi = recompute_after_skip(
                    remaining,
                    debt.interest_rate or 0.0,
                    debt.interest_type or "NONE",
                    periods,
                )
                debt.emi_amount = new_emi
            return
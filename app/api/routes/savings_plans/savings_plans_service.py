from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.savings_plans.model import (
    FamilySavingsPlan,
    FamilySavingsPlanContribution,
    PersonalSavingsPlan,
    PersonalSavingsPlanContribution,
)
from app.api.routes.savings_plans.savings_plans_schemas import (
    SavingsPlanContributionCreateRequest,
    SavingsPlanCreateRequest,
    SavingsPlanUpdateRequest,
)
from app.api.routes.scheduler.model import ScheduledJob
from app.api.schemas.pagination import PaginationParams
from app.core.scope import ScopeContext, filter_entity_rows
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_SCHEDULED,
    JOB_STATUS_SKIPPED,
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_CONTRIBUTION,
    PREPAY_MODE_CLEAR_UPCOMING,
    PREPAY_MODE_KEEP_EMI_REDUCE_TENURE,
    PREPAY_MODE_REDUCE_EMI,
)
from app.core.date_advance import advance_next_date
from app.core.emi_recompute import recompute_plan_contribution
from app.core.savings_ledger_service import SavingsLedgerService
from app.core.transfer_pools import scope_to_pool

SOURCE_FAMILY_SAVINGS_PLAN = "FAMILY_SAVINGS_PLAN"
SOURCE_PERSONAL_SAVINGS_PLAN = "PERSONAL_SAVINGS_PLAN"


def _source_type(plan: FamilySavingsPlan | PersonalSavingsPlan) -> str:
    return SOURCE_PERSONAL_SAVINGS_PLAN if isinstance(plan, PersonalSavingsPlan) else SOURCE_FAMILY_SAVINGS_PLAN


class SavingsPlansService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_plans(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[object, bool]], int]:
        family_rows = list(
            (await self.pg_session.execute(
                select(FamilySavingsPlan).where(FamilySavingsPlan.family_id == family_id)
            )).scalars().all()
        )
        personal_rows = list(
            (await self.pg_session.execute(
                select(PersonalSavingsPlan).where(PersonalSavingsPlan.family_id == family_id)
            )).scalars().all()
        )
        combined = [(p, False) for p in family_rows] + [(p, True) for p in personal_rows]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].created_at, reverse=True)
        total = len(combined)
        return combined[pagination.offset : pagination.offset + pagination.page_size], total

    async def list_plan_history(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[object, bool]], int]:
        family_rows = list(
            (
                await self.pg_session.execute(
                    select(FamilySavingsPlan).where(
                        FamilySavingsPlan.family_id == family_id,
                        FamilySavingsPlan.status.in_(["COMPLETED", "CANCELLED"]),
                    )
                )
            ).scalars().all()
        )
        personal_rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalSavingsPlan).where(
                        PersonalSavingsPlan.family_id == family_id,
                        PersonalSavingsPlan.status.in_(["COMPLETED", "CANCELLED"]),
                    )
                )
            ).scalars().all()
        )
        combined = [(p, False) for p in family_rows] + [(p, True) for p in personal_rows]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].created_at, reverse=True)
        total = len(combined)
        return combined[pagination.offset : pagination.offset + pagination.page_size], total

    async def list_personal_plans(
        self, user_id: UUID, pagination: PaginationParams, *, status: str | None = "ACTIVE"
    ) -> tuple[list[PersonalSavingsPlan], int]:
        stmt = select(PersonalSavingsPlan).where(PersonalSavingsPlan.user_id == user_id)
        if status:
            stmt = stmt.where(PersonalSavingsPlan.status == status)
        rows = list((await self.pg_session.execute(stmt)).scalars().all())
        rows.sort(key=lambda x: x.created_at, reverse=True)
        total = len(rows)
        return rows[pagination.offset : pagination.offset + pagination.page_size], total

    async def get_personal_plan(
        self, plan_id: UUID, user_id: UUID
    ) -> PersonalSavingsPlan | None:
        return (
            await self.pg_session.execute(
                select(PersonalSavingsPlan).where(
                    PersonalSavingsPlan.id == plan_id,
                    PersonalSavingsPlan.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def create_personal_plan(
        self, user_id: UUID, family_id: UUID, request: SavingsPlanCreateRequest
    ) -> PersonalSavingsPlan:
        plan, _ = await self.create_plan(
            family_id, user_id, request.model_copy(update={"is_personal": True})
        )
        return plan  # type: ignore[return-value]

    @staticmethod
    def _emi_config(request: SavingsPlanCreateRequest) -> dict:
        """Optional sinking-fund / EMI fields that were provided on the request."""
        cfg: dict = {}
        for field in (
            "purpose_type",
            "linked_type",
            "linked_id",
            "target_frequency",
            "next_target_date",
            "contribution_amount",
            "contribution_every",
            "next_contribution_date",
            "auto_deduct",
            "confirm_contributions",
            "requires_confirmation",
            "skip_fine_amount",
            "emi_mode",
        ):
            value = getattr(request, field, None)
            if value is not None:
                cfg[field] = value
        return cfg

    async def create_plan(
        self, family_id: UUID, user_id: UUID, request: SavingsPlanCreateRequest
    ) -> tuple[FamilySavingsPlan | PersonalSavingsPlan, bool]:
        cfg = self._emi_config(request)
        if request.is_personal:
            plan = PersonalSavingsPlan(
                family_id=family_id,
                user_id=user_id,
                scope_type=request.scope_type,
                plan_name=request.plan_name,
                target_amount=request.target_amount,
                access_level=request.access_level or "PRIVATE",
                **cfg,
            )
            source_type = "PERSONAL_SAVINGS_PLAN"
            is_personal = True
        else:
            plan = FamilySavingsPlan(
                family_id=family_id,
                scope_type=request.scope_type,
                plan_name=request.plan_name,
                target_amount=request.target_amount,
                access_level=request.access_level or "FAMILY",
                **cfg,
            )
            source_type = "FAMILY_SAVINGS_PLAN"
            is_personal = False

        self.pg_session.add(plan)
        await self.pg_session.flush()

        if getattr(request, "splitLines", None):
            from app.core.funding_service import FundingService

            await FundingService(self.pg_session).save_split_plan(
                source_type,
                plan.id,
                [
                    {"pool_type": sl.poolType, "family_id": sl.familyId, "amount": sl.amount}
                    for sl in request.splitLines
                ],
            )

        from app.scheduler.savings_plan_cron import create_or_replace_next_contrib_job

        await create_or_replace_next_contrib_job(self.pg_session, plan, source_type)
        await self.pg_session.commit()
        await self.pg_session.refresh(plan)
        return plan, is_personal

    async def get_plan(
        self, plan_id: UUID, family_id: UUID
    ) -> tuple[FamilySavingsPlan | PersonalSavingsPlan, bool] | None:
        for model, is_personal in ((FamilySavingsPlan, False), (PersonalSavingsPlan, True)):
            row = (await self.pg_session.execute(
                select(model).where(model.id == plan_id, model.family_id == family_id)
            )).scalar_one_or_none()
            if row:
                return row, is_personal
        return None

    async def update_plan(
        self, plan: FamilySavingsPlan | PersonalSavingsPlan, request: SavingsPlanUpdateRequest
    ) -> FamilySavingsPlan | PersonalSavingsPlan:
        is_personal = isinstance(plan, PersonalSavingsPlan)
        source_type = "PERSONAL_SAVINGS_PLAN" if is_personal else "FAMILY_SAVINGS_PLAN"
        data = request.model_dump(exclude_none=True, exclude={"splitLines"})
        for field, value in data.items():
            setattr(plan, field, value)

        if request.splitLines is not None:
            from app.core.funding_service import FundingService

            await FundingService(self.pg_session).save_split_plan(
                source_type,
                plan.id,
                [
                    {"pool_type": sl.poolType, "family_id": sl.familyId, "amount": sl.amount}
                    for sl in request.splitLines
                ],
            )

        from app.core.constants import (
            JOB_STATUS_AWAITING_CONFIRMATION,
            JOB_STATUS_CANCELLED,
            JOB_STATUS_SCHEDULED,
        )
        from sqlalchemy import update as sa_update

        if plan.status in ("ACTIVE", "PAUSED") and plan.contribution_amount and plan.next_contribution_date:
            from app.scheduler.savings_plan_cron import create_or_replace_next_contrib_job

            await create_or_replace_next_contrib_job(self.pg_session, plan, source_type)
        else:
            await self.pg_session.execute(
                sa_update(ScheduledJob)
                .where(
                    ScheduledJob.source_type == source_type,
                    ScheduledJob.source_id == plan.id,
                    ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
                )
                .values(status=JOB_STATUS_CANCELLED)
            )

        await self.pg_session.commit()
        await self.pg_session.refresh(plan)
        return plan

    async def delete_plan(self, plan: FamilySavingsPlan | PersonalSavingsPlan) -> None:
        is_personal = isinstance(plan, PersonalSavingsPlan)
        source_type = "PERSONAL_SAVINGS_PLAN" if is_personal else "FAMILY_SAVINGS_PLAN"
        from app.core.constants import (
            JOB_STATUS_AWAITING_CONFIRMATION,
            JOB_STATUS_CANCELLED,
            JOB_STATUS_SCHEDULED,
        )
        from sqlalchemy import update as sa_update

        # Refund accumulated funds back to the owning pool before deleting.
        if plan.accumulated_amount and plan.accumulated_amount > Decimal("0"):
            from app.core.savings_ledger_service import SavingsLedgerService
            from app.core.constants import LEDGER_IN, LEDGER_SOURCE_CONTRIBUTION
            from app.core.transfer_pools import scope_to_pool

            pool = scope_to_pool(
                plan.scope_type,
                family_id=plan.family_id,
                user_id=getattr(plan, "user_id", None) if is_personal else None,
            )
            ledger = SavingsLedgerService(self.pg_session)
            await ledger.apply_movement(
                pool,
                plan.accumulated_amount,
                LEDGER_IN,
                LEDGER_SOURCE_CONTRIBUTION,
                source_id=plan.id,
                description=f"Refund — {plan.plan_name} (plan removed)",
            )

        await self.pg_session.execute(
            sa_update(ScheduledJob)
            .where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == plan.id,
                ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
            )
            .values(status=JOB_STATUS_CANCELLED)
        )
        plan.status = "CANCELLED"
        plan.completed_at = datetime.now(timezone.utc)
        await self.pg_session.commit()

    async def list_contributions(
        self, plan_id: UUID, family_id: UUID, is_personal: bool
    ) -> list[FamilySavingsPlanContribution | PersonalSavingsPlanContribution]:
        model = (
            PersonalSavingsPlanContribution if is_personal else FamilySavingsPlanContribution
        )
        stmt = (
            select(model)
            .where(model.plan_id == plan_id, model.family_id == family_id)
            .order_by(model.contribution_date.desc())
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def add_contribution(
        self,
        plan: FamilySavingsPlan | PersonalSavingsPlan,
        is_personal: bool,
        user_id: UUID,
        request: SavingsPlanContributionCreateRequest,
    ) -> FamilySavingsPlanContribution | PersonalSavingsPlanContribution:
        when = request.contribution_date or datetime.now(timezone.utc)
        amount = request.amount
        delta = amount if request.direction == "IN" else -amount
        plan.accumulated_amount = max(Decimal("0"), plan.accumulated_amount + delta)

        if is_personal:
            contrib = PersonalSavingsPlanContribution(
                family_id=plan.family_id,
                scope_type=plan.scope_type,
                plan_id=plan.id,
                user_id=user_id,
                amount=amount,
                direction=request.direction,
                contribution_date=when,
                source_type="MANUAL",
            )
        else:
            contrib = FamilySavingsPlanContribution(
                family_id=plan.family_id,
                scope_type=plan.scope_type,
                plan_id=plan.id,
                contributed_by=user_id,
                amount=amount,
                direction=request.direction,
                contribution_date=when,
                source_type="MANUAL",
            )
        self.pg_session.add(contrib)
        await self.pg_session.flush()

        ledger = SavingsLedgerService(self.pg_session)
        pool = scope_to_pool(
            plan.scope_type,
            family_id=plan.family_id,
            user_id=getattr(plan, "user_id", None) if is_personal else None,
        )
        direction = LEDGER_OUT if request.direction == "IN" else LEDGER_IN
        await ledger.apply_movement(
            pool,
            amount,
            direction,
            LEDGER_SOURCE_CONTRIBUTION,
            source_id=contrib.id,
            occurred_at=when,
        )
        await self.pg_session.commit()
        await self.pg_session.refresh(contrib)
        return contrib

    async def _skip_next_plan_job(
        self, plan: FamilySavingsPlan | PersonalSavingsPlan, is_personal: bool
    ) -> None:
        source_type = (
            "PERSONAL_SAVINGS_PLAN" if is_personal else "FAMILY_SAVINGS_PLAN"
        )
        stmt = (
            select(ScheduledJob)
            .where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == plan.id,
                ScheduledJob.status.in_(
                    [JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]
                ),
            )
            .order_by(ScheduledJob.scheduled_for.asc())
        )
        job = (await self.pg_session.execute(stmt)).scalars().first()
        if job is not None:
            job.status = JOB_STATUS_SKIPPED
        if plan.next_contribution_date is not None:
            plan.next_contribution_date = advance_next_date(
                plan.next_contribution_date, every=plan.contribution_every
            )

    async def prepay_plan(
        self,
        plan: FamilySavingsPlan | PersonalSavingsPlan,
        is_personal: bool,
        user_id: UUID,
        amount: Decimal,
        mode: str | None,
        contribution_date: datetime | None = None,
    ) -> FamilySavingsPlan | PersonalSavingsPlan:
        """Add money to the fund early, then optionally clear or reduce future EMIs."""
        await self.add_contribution(
            plan,
            is_personal,
            user_id,
            SavingsPlanContributionCreateRequest(
                amount=amount, direction="IN", contribution_date=contribution_date
            ),
        )
        # add_contribution committed and refreshed plan.accumulated_amount.
        if mode == PREPAY_MODE_CLEAR_UPCOMING:
            await self._skip_next_plan_job(plan, is_personal)
        elif mode == PREPAY_MODE_REDUCE_EMI:
            plan.contribution_amount = recompute_plan_contribution(plan)
        await self.pg_session.commit()
        await self.pg_session.refresh(plan)
        return plan

    async def part_payment(
        self,
        plan: FamilySavingsPlan | PersonalSavingsPlan,
        *,
        amount: Decimal,
        mode: str = PREPAY_MODE_REDUCE_EMI,
        split_lines: list | None = None,
        paid_externally: bool = False,
    ) -> FamilySavingsPlan | PersonalSavingsPlan:
        from app.core.funding_service import FundingService, SplitLine

        if amount <= Decimal("0"):
            raise ValueError("Part payment amount must be positive")

        source_type = _source_type(plan)
        when = datetime.now(timezone.utc)
        fs = FundingService(self.pg_session)
        if paid_externally:
            await fs.execute_paid_externally(
                entity_type=source_type,
                entity_id=plan.id,
                amount=amount,
                description=f"Part payment (paid externally) — {plan.plan_name}",
                occurred_at=when,
            )
        elif split_lines:
            lines = [
                SplitLine(pool_type=ln.pool_type, amount=ln.amount, family_id=ln.family_id)
                for ln in split_lines
            ]
            await fs.execute_debit(
                lines,
                amount,
                ledger_source_type=LEDGER_SOURCE_CONTRIBUTION,
                entity_type=source_type,
                entity_id=plan.id,
                description=f"Part payment — {plan.plan_name}",
                occurred_at=when,
            )
        else:
            plan_lines = await fs.load_split_plan(source_type, plan.id)
            if plan_lines:
                lines = [
                    SplitLine(pool_type=sl.pool_type, amount=sl.amount, family_id=sl.family_id)
                    for sl in plan_lines
                ]
                await fs.execute_debit(
                    lines,
                    amount,
                    ledger_source_type=LEDGER_SOURCE_CONTRIBUTION,
                    entity_type=source_type,
                    entity_id=plan.id,
                    description=f"Part payment — {plan.plan_name}",
                    occurred_at=when,
                )
            else:
                pool = scope_to_pool(
                    plan.scope_type,
                    family_id=plan.family_id,
                    user_id=getattr(plan, "user_id", None),
                )
                ledger = SavingsLedgerService(self.pg_session)
                await ledger.apply_movement(
                    pool,
                    amount,
                    LEDGER_OUT,
                    LEDGER_SOURCE_CONTRIBUTION,
                    source_id=plan.id,
                    description=f"Part payment — {plan.plan_name}",
                    occurred_at=when,
                )

        plan.accumulated_amount = plan.accumulated_amount + amount
        is_personal = isinstance(plan, PersonalSavingsPlan)
        if is_personal:
            self.pg_session.add(
                PersonalSavingsPlanContribution(
                    family_id=plan.family_id,
                    scope_type=plan.scope_type,
                    plan_id=plan.id,
                    user_id=plan.user_id,
                    amount=amount,
                    direction="IN",
                    contribution_date=when,
                    source_type="PART_PAYMENT",
                )
            )
        else:
            self.pg_session.add(
                FamilySavingsPlanContribution(
                    family_id=plan.family_id,
                    scope_type=plan.scope_type,
                    plan_id=plan.id,
                    contributed_by=getattr(plan, "user_id", None),
                    amount=amount,
                    direction="IN",
                    contribution_date=when,
                    source_type="PART_PAYMENT",
                )
            )

        if mode == PREPAY_MODE_REDUCE_EMI:
            plan.contribution_amount = recompute_plan_contribution(plan)
        elif mode != PREPAY_MODE_KEEP_EMI_REDUCE_TENURE:
            raise ValueError(f"Unknown part-payment mode: {mode}")

        from app.scheduler.savings_plan_cron import (
            check_completion,
            create_or_replace_next_contrib_job,
        )

        await create_or_replace_next_contrib_job(self.pg_session, plan, source_type)
        await check_completion(self.pg_session, plan, source_type)
        await self.pg_session.commit()
        await self.pg_session.refresh(plan)
        return plan

    async def payout(
        self,
        plan: FamilySavingsPlan | PersonalSavingsPlan,
        *,
        amount: Decimal,
        user_id: UUID,
        note: str | None = None,
    ) -> FamilySavingsPlan | PersonalSavingsPlan:
        if amount <= Decimal("0"):
            raise ValueError("Payout amount must be positive")
        if plan.accumulated_amount < amount:
            raise ValueError("Insufficient plan balance for payout")

        when = datetime.now(timezone.utc)
        is_personal = isinstance(plan, PersonalSavingsPlan)
        plan.accumulated_amount = plan.accumulated_amount - amount
        if is_personal:
            self.pg_session.add(
                PersonalSavingsPlanContribution(
                    family_id=plan.family_id,
                    scope_type=plan.scope_type,
                    plan_id=plan.id,
                    user_id=user_id,
                    amount=amount,
                    direction="OUT",
                    contribution_date=when,
                    source_type="PAYOUT",
                )
            )
        else:
            self.pg_session.add(
                FamilySavingsPlanContribution(
                    family_id=plan.family_id,
                    scope_type=plan.scope_type,
                    plan_id=plan.id,
                    contributed_by=user_id,
                    amount=amount,
                    direction="OUT",
                    contribution_date=when,
                    source_type="PAYOUT",
                )
            )

        source_type = _source_type(plan)
        if plan.target_frequency and plan.next_target_date:
            plan.next_target_date = advance_next_date(
                plan.next_target_date, every=plan.target_frequency
            )
            plan.status = "ACTIVE"
        else:
            plan.status = "COMPLETED"
            plan.completed_at = when
            from sqlalchemy import update as sa_update
            from app.core.constants import JOB_STATUS_CANCELLED

            await self.pg_session.execute(
                sa_update(ScheduledJob)
                .where(
                    ScheduledJob.source_type == source_type,
                    ScheduledJob.source_id == plan.id,
                    ScheduledJob.status.in_(
                        [JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]
                    ),
                )
                .values(status=JOB_STATUS_CANCELLED)
            )

        await self.pg_session.commit()
        await self.pg_session.refresh(plan)
        return plan

    async def list_defaults(
        self, plan: FamilySavingsPlan | PersonalSavingsPlan
    ) -> tuple[list, Decimal]:
        from app.core.default_bucket_service import DefaultBucketEntry, DefaultBucketService

        svc = DefaultBucketService(self.pg_session)
        items = await svc.list_open(_source_type(plan), plan.id)
        stmt = select(DefaultBucketEntry).where(
            DefaultBucketEntry.entity_type == _source_type(plan),
            DefaultBucketEntry.entity_id == plan.id,
        )
        all_items = list((await self.pg_session.execute(stmt)).scalars().all())
        total_open = sum((i.amount + i.fine_amount for i in items), Decimal("0"))
        return all_items, total_open

    async def settle_default(
        self, entry_id: UUID, *, split_lines: list[dict] | None = None, note: str | None = None
    ):
        from app.core.default_bucket_service import DefaultBucketService
        from app.scheduler.savings_plan_cron import check_completion

        svc = DefaultBucketService(self.pg_session)
        entry = await svc.settle(entry_id, split_lines=split_lines, note=note)
        plan = (
            await self.pg_session.execute(
                select(FamilySavingsPlan).where(FamilySavingsPlan.id == entry.entity_id)
            )
        ).scalar_one_or_none() or (
            await self.pg_session.execute(
                select(PersonalSavingsPlan).where(PersonalSavingsPlan.id == entry.entity_id)
            )
        ).scalar_one_or_none()
        if plan is not None:
            await check_completion(self.pg_session, plan, entry.entity_type)
        await self.pg_session.commit()
        return entry

    async def waive_default(self, entry_id: UUID, *, note: str | None = None):
        from app.core.default_bucket_service import DefaultBucketService
        from app.scheduler.savings_plan_cron import check_completion

        svc = DefaultBucketService(self.pg_session)
        entry = await svc.waive(entry_id, note=note)
        plan = (
            await self.pg_session.execute(
                select(FamilySavingsPlan).where(FamilySavingsPlan.id == entry.entity_id)
            )
        ).scalar_one_or_none() or (
            await self.pg_session.execute(
                select(PersonalSavingsPlan).where(PersonalSavingsPlan.id == entry.entity_id)
            )
        ).scalar_one_or_none()
        if plan is not None:
            await check_completion(self.pg_session, plan, entry.entity_type)
        await self.pg_session.commit()
        return entry

    async def link_candidates(
        self, family_id: UUID, purpose_type: str, *, user_id: UUID | None = None
    ) -> list[dict]:
        from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
        from app.api.routes.debt.model import Debt, DebtScopeView
        from app.api.routes.expense.model import FamilyExpense, PersonalExpense
        from app.api.routes.investments.model import FamilyInvestment, PersonalInvestment

        candidates: list[dict] = []
        if purpose_type == "INSURANCE":
            for model, is_personal in ((FamilyInsurance, False), (PersonalInsurance, True)):
                stmt = select(model).where(model.family_id == family_id, model.status == "ACTIVE")
                if is_personal and user_id:
                    stmt = stmt.where(model.user_id == user_id)
                for ins in (await self.pg_session.execute(stmt)).scalars().all():
                    candidates.append(
                        {
                            "id": ins.id,
                            "name": ins.insurance_name,
                            "amount": ins.premium_amount,
                            "nextDate": ins.next_premium_date,
                        }
                    )
        elif purpose_type == "DEBT":
            visibility = and_(
                DebtScopeView.scope_kind == "FAMILY",
                DebtScopeView.family_id == family_id,
                DebtScopeView.user_id.is_(None),
                DebtScopeView.excluded.is_(False),
            )
            if user_id is not None:
                visibility = or_(
                    visibility,
                    and_(
                        DebtScopeView.scope_kind == "PERSONAL",
                        DebtScopeView.user_id == user_id,
                        DebtScopeView.excluded.is_(False),
                    ),
                )
            stmt = (
                select(Debt)
                .join(DebtScopeView, DebtScopeView.debt_id == Debt.id)
                .where(Debt.status == "ACTIVE", visibility)
                .distinct()
            )
            for debt in (await self.pg_session.execute(stmt)).scalars().all():
                candidates.append(
                    {
                        "id": debt.id,
                        "name": debt.debt_name,
                        "amount": debt.remaining_amount,
                        "nextDate": debt.emi_next_date,
                    }
                )
        elif purpose_type == "EXPENSE":
            for model, is_personal in ((FamilyExpense, False), (PersonalExpense, True)):
                stmt = select(model).where(
                    model.family_id == family_id, model.is_recurring.is_(True)
                )
                if is_personal and user_id:
                    stmt = stmt.where(model.user_id == user_id)
                for exp in (await self.pg_session.execute(stmt)).scalars().all():
                    candidates.append(
                        {
                            "id": exp.id,
                            "name": exp.expense_name,
                            "amount": exp.amount,
                            "nextDate": exp.next_payment_date,
                        }
                    )
        elif purpose_type == "INVESTMENT":
            for model, is_personal in ((FamilyInvestment, False), (PersonalInvestment, True)):
                stmt = select(model).where(model.family_id == family_id, model.status == "ACTIVE")
                if is_personal and user_id:
                    stmt = stmt.where(model.user_id == user_id)
                for inv in (await self.pg_session.execute(stmt)).scalars().all():
                    candidates.append(
                        {
                            "id": inv.id,
                            "name": inv.investment_name,
                            "amount": inv.contribution_amount or inv.initial_lump_sum or Decimal("0"),
                            "nextDate": inv.next_contribution_date,
                        }
                    )
        for c in candidates:
            c["suggestedContribution"] = (
                recompute_plan_contribution(
                    type(
                        "P",
                        (),
                        {
                            "target_amount": c["amount"],
                            "accumulated_amount": Decimal("0"),
                            "next_contribution_date": datetime.now(timezone.utc),
                            "next_target_date": c["nextDate"],
                            "contribution_every": "MONTHLY",
                        },
                    )()
                )
                if c.get("nextDate")
                else c["amount"]
            )
        return candidates

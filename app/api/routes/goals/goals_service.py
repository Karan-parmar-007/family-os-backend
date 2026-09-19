from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.expense.model import FamilyExpenseLog, PersonalExpenseLog
from app.api.routes.family_income.model import FamilyIncomeLog, PersonalIncomeLog
from app.api.routes.goals.goals_schemas import (
    GoalContributionCreateRequest,
    GoalCreateRequest,
    GoalUpdateRequest,
    GoalWithdrawRequest,
)
from app.api.routes.goals.model import (
    FamilyGoal,
    FamilyGoalContribution,
    PersonalGoal,
    PersonalGoalContribution,
)
from app.api.routes.scheduler.model import Notification
from app.api.schemas.pagination import PaginationParams
from app.core.constants import (
    ACTION_ACCEPT,
    ACTION_DISMISS,
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_GOAL_CONTRIB,
    NOTIF_STATUS_UNREAD,
)
from app.core.funding_service import FundingService, InsufficientFundsError
from app.core.savings_ledger_service import SavingsLedgerService
from app.core.scope import ScopeContext, filter_entity_rows
from app.core.transfer_pools import scope_to_pool

SOURCE_FAMILY_GOAL = "FAMILY_GOAL"
SOURCE_PERSONAL_GOAL = "PERSONAL_GOAL"


class GoalsService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_goals(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
        status: str | None = "ACTIVE",
    ) -> tuple[list[tuple[object, bool]], int]:
        family_stmt = select(FamilyGoal).where(FamilyGoal.family_id == family_id)
        personal_stmt = select(PersonalGoal).where(PersonalGoal.family_id == family_id)
        if status:
            family_stmt = family_stmt.where(FamilyGoal.status == status)
            personal_stmt = personal_stmt.where(PersonalGoal.status == status)
        family_rows = list((await self.pg_session.execute(family_stmt)).scalars().all())
        personal_rows = list((await self.pg_session.execute(personal_stmt)).scalars().all())
        combined = [(g, False) for g in family_rows] + [(g, True) for g in personal_rows]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].created_at, reverse=True)
        total = len(combined)
        return combined[pagination.offset : pagination.offset + pagination.page_size], total

    async def list_history(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[object, bool]], int]:
        family_rows = list(
            (
                await self.pg_session.execute(
                    select(FamilyGoal).where(
                        FamilyGoal.family_id == family_id,
                        FamilyGoal.status.in_(("ACHIEVED", "CANCELLED")),
                    )
                )
            ).scalars().all()
        )
        personal_rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalGoal).where(
                        PersonalGoal.family_id == family_id,
                        PersonalGoal.status.in_(("ACHIEVED", "CANCELLED")),
                    )
                )
            ).scalars().all()
        )
        combined = [(g, False) for g in family_rows] + [(g, True) for g in personal_rows]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].updated_at, reverse=True)
        total = len(combined)
        return combined[pagination.offset : pagination.offset + pagination.page_size], total

    async def list_personal_goals(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = "ACTIVE",
    ) -> tuple[list[PersonalGoal], int]:
        stmt = select(PersonalGoal).where(PersonalGoal.user_id == user_id)
        if status:
            stmt = stmt.where(PersonalGoal.status == status)
        rows = list((await self.pg_session.execute(stmt)).scalars().all())
        rows.sort(key=lambda g: g.created_at, reverse=True)
        total = len(rows)
        return rows[pagination.offset : pagination.offset + pagination.page_size], total

    async def create_goal(
        self, family_id: UUID, user_id: UUID, request: GoalCreateRequest
    ) -> tuple[FamilyGoal | PersonalGoal, bool]:
        if request.is_personal:
            goal = PersonalGoal(
                family_id=family_id,
                user_id=user_id,
                scope_type=request.scope_type,
                goal_name=request.goal_name,
                target_amount=request.target_amount,
                notes=request.notes,
                document_id=request.document_id,
                access_level=request.access_level or "PRIVATE",
            )
            self.pg_session.add(goal)
            await self.pg_session.commit()
            await self.pg_session.refresh(goal)
            return goal, True
        goal = FamilyGoal(
            family_id=family_id,
            scope_type=request.scope_type,
            goal_name=request.goal_name,
            target_amount=request.target_amount,
            notes=request.notes,
            document_id=request.document_id,
            access_level=request.access_level or "FAMILY",
        )
        self.pg_session.add(goal)
        await self.pg_session.commit()
        await self.pg_session.refresh(goal)
        return goal, False

    async def create_personal_goal(
        self, user_id: UUID, family_id: UUID, request: GoalCreateRequest
    ) -> PersonalGoal:
        goal, _ = await self.create_goal(family_id, user_id, request.model_copy(update={"is_personal": True}))
        return goal  # type: ignore[return-value]

    async def get_goal(
        self, goal_id: UUID, family_id: UUID
    ) -> tuple[FamilyGoal | PersonalGoal, bool] | None:
        for model, is_personal in ((FamilyGoal, False), (PersonalGoal, True)):
            row = (
                await self.pg_session.execute(
                    select(model).where(model.id == goal_id, model.family_id == family_id)
                )
            ).scalar_one_or_none()
            if row:
                return row, is_personal
        return None

    async def get_personal_goal(
        self, goal_id: UUID, user_id: UUID
    ) -> PersonalGoal | None:
        return (
            await self.pg_session.execute(
                select(PersonalGoal).where(
                    PersonalGoal.id == goal_id, PersonalGoal.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    async def update_goal(
        self, goal: FamilyGoal | PersonalGoal, request: GoalUpdateRequest
    ) -> FamilyGoal | PersonalGoal:
        for field, value in request.model_dump(exclude_none=True).items():
            setattr(goal, field, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(goal)
        return goal

    async def delete_goal(
        self, goal: FamilyGoal | PersonalGoal, is_personal: bool, user_id: UUID
    ) -> None:
        if goal.collected_amount > 0:
            await self._credit_pool(
                goal,
                is_personal,
                goal.collected_amount,
                user_id,
                income_name=f"Goal refund — {goal.goal_name}",
            )
            goal.collected_amount = Decimal("0")
        goal.status = "CANCELLED"
        goal.completed_at = datetime.now(timezone.utc)
        await self.pg_session.commit()

    async def list_contributions(
        self, goal_id: UUID, family_id: UUID, is_personal: bool
    ) -> list[FamilyGoalContribution | PersonalGoalContribution]:
        model = PersonalGoalContribution if is_personal else FamilyGoalContribution
        stmt = (
            select(model)
            .where(model.goal_id == goal_id, model.family_id == family_id)
            .order_by(model.contribution_date.desc())
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def add_contribution(
        self,
        goal: FamilyGoal | PersonalGoal,
        is_personal: bool,
        user_id: UUID,
        request: GoalContributionCreateRequest,
    ) -> FamilyGoalContribution | PersonalGoalContribution:
        if goal.status != "ACTIVE":
            raise ValueError("Goal is not active")
        when = request.contribution_date or datetime.now(timezone.utc)
        amount = request.amount
        entity_type = SOURCE_PERSONAL_GOAL if is_personal else SOURCE_FAMILY_GOAL
        pool = scope_to_pool(
            goal.scope_type,
            family_id=goal.family_id,
            user_id=getattr(goal, "user_id", None) if is_personal else None,
        )
        fs = FundingService(self.pg_session)
        try:
            await fs.execute_debit_adhoc(
                pool,
                amount,
                ledger_source_type=LEDGER_SOURCE_GOAL_CONTRIB,
                entity_type=entity_type,
                entity_id=goal.id,
                description=f"Goal — {goal.goal_name}",
                occurred_at=when,
            )
        except InsufficientFundsError as exc:
            raise ValueError(str(exc)) from exc

        goal.collected_amount = goal.collected_amount + amount
        if is_personal:
            contrib = PersonalGoalContribution(
                family_id=goal.family_id,
                scope_type=goal.scope_type,
                goal_id=goal.id,
                user_id=user_id,
                amount=amount,
                direction="IN",
                note=request.note,
                contribution_date=when,
                source_type="MANUAL",
            )
            self.pg_session.add(
                PersonalExpenseLog(
                    family_id=goal.family_id,
                    user_id=user_id,
                    logged_by=user_id,
                    expense_name=f"Goal — {goal.goal_name}",
                    amount=amount,
                    expense_date=when,
                    source_type="GOAL_CONTRIB",
                    source_id=goal.id,
                )
            )
        else:
            contrib = FamilyGoalContribution(
                family_id=goal.family_id,
                scope_type=goal.scope_type,
                goal_id=goal.id,
                contributed_by=user_id,
                amount=amount,
                direction="IN",
                note=request.note,
                contribution_date=when,
                source_type="MANUAL",
            )
            self.pg_session.add(
                FamilyExpenseLog(
                    family_id=goal.family_id,
                    scope_type=goal.scope_type,
                    logged_by=user_id,
                    expense_name=f"Goal — {goal.goal_name}",
                    amount=amount,
                    expense_date=when,
                    source_type="GOAL_CONTRIB",
                    source_id=goal.id,
                )
            )
        self.pg_session.add(contrib)
        await self.pg_session.flush()
        await self._maybe_achieve(goal, is_personal, user_id)
        await self.pg_session.commit()
        await self.pg_session.refresh(contrib)
        return contrib

    async def withdraw(
        self,
        goal: FamilyGoal | PersonalGoal,
        is_personal: bool,
        user_id: UUID,
        request: GoalWithdrawRequest,
    ) -> FamilyGoalContribution | PersonalGoalContribution:
        if goal.status != "ACTIVE":
            raise ValueError("Goal is not active")
        amount = request.amount
        if amount > goal.collected_amount:
            raise ValueError("Withdrawal exceeds collected amount")
        when = datetime.now(timezone.utc)
        goal.collected_amount = goal.collected_amount - amount
        await self._credit_pool(
            goal,
            is_personal,
            amount,
            user_id,
            income_name=f"Goal withdraw — {goal.goal_name}",
            occurred_at=when,
        )
        if is_personal:
            contrib = PersonalGoalContribution(
                family_id=goal.family_id,
                scope_type=goal.scope_type,
                goal_id=goal.id,
                user_id=user_id,
                amount=amount,
                direction="OUT",
                note=request.note,
                contribution_date=when,
                source_type="MANUAL",
            )
        else:
            contrib = FamilyGoalContribution(
                family_id=goal.family_id,
                scope_type=goal.scope_type,
                goal_id=goal.id,
                contributed_by=user_id,
                amount=amount,
                direction="OUT",
                note=request.note,
                contribution_date=when,
                source_type="MANUAL",
            )
        self.pg_session.add(contrib)
        await self.pg_session.commit()
        await self.pg_session.refresh(contrib)
        return contrib

    async def release_achieved_goal(
        self, goal: FamilyGoal | PersonalGoal, is_personal: bool, user_id: UUID
    ) -> None:
        if goal.status != "ACHIEVED":
            raise ValueError("Goal is not achieved")
        if goal.collected_amount <= 0:
            return
        amount = goal.collected_amount
        await self._credit_pool(
            goal,
            is_personal,
            amount,
            user_id,
            income_name=f"Goal release — {goal.goal_name}",
        )
        goal.collected_amount = Decimal("0")
        await self.pg_session.commit()

    async def _maybe_achieve(
        self, goal: FamilyGoal | PersonalGoal, is_personal: bool, user_id: UUID
    ) -> None:
        if goal.collected_amount < goal.target_amount:
            return
        goal.status = "ACHIEVED"
        goal.completed_at = datetime.now(timezone.utc)
        notify_user = getattr(goal, "user_id", user_id) if is_personal else user_id
        self.pg_session.add(
            Notification(
                user_id=notify_user,
                family_id=goal.family_id,
                type="GOAL_ACHIEVED",
                title=f"Goal achieved: {goal.goal_name}",
                body="Release reserved funds back to your savings pool?",
                related_entity_type=SOURCE_PERSONAL_GOAL if is_personal else SOURCE_FAMILY_GOAL,
                related_entity_id=goal.id,
                allowed_actions={"actions": [ACTION_ACCEPT, ACTION_DISMISS]},
                status=NOTIF_STATUS_UNREAD,
            )
        )

    async def _credit_pool(
        self,
        goal: FamilyGoal | PersonalGoal,
        is_personal: bool,
        amount: Decimal,
        user_id: UUID,
        *,
        income_name: str,
        occurred_at: datetime | None = None,
    ) -> None:
        when = occurred_at or datetime.now(timezone.utc)
        pool = scope_to_pool(
            goal.scope_type,
            family_id=goal.family_id,
            user_id=getattr(goal, "user_id", None) if is_personal else None,
        )
        ledger = SavingsLedgerService(self.pg_session)
        entity_type = SOURCE_PERSONAL_GOAL if is_personal else SOURCE_FAMILY_GOAL
        await ledger.apply_movement(
            pool,
            amount,
            LEDGER_IN,
            LEDGER_SOURCE_GOAL_CONTRIB,
            source_id=goal.id,
            description=income_name,
            occurred_at=when,
        )
        if is_personal:
            self.pg_session.add(
                PersonalIncomeLog(
                    family_id=goal.family_id,
                    user_id=getattr(goal, "user_id", user_id),
                    logged_by=user_id,
                    income_name=income_name,
                    amount=amount,
                    income_date=when,
                    source_type="GOAL_CONTRIB",
                    source_id=goal.id,
                )
            )
        else:
            self.pg_session.add(
                FamilyIncomeLog(
                    family_id=goal.family_id,
                    scope_type=goal.scope_type,
                    logged_by=user_id,
                    income_name=income_name,
                    total_amount=amount,
                    family_amount=amount,
                    income_date=when,
                    source_type="GOAL_CONTRIB",
                    source_id=goal.id,
                    added_by_user_id=user_id,
                )
            )

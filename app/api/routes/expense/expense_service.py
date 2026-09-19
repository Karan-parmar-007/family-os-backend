import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.expense.expense_schemas import (
    ExpenseCategoryCreateRequest,
    ExpenseLogCreateRequest,
    ExpenseLogUpdateRequest,
    ExpenseRecurringCreateRequest,
    ExpenseRecurringUpdateRequest,
)
from app.api.schemas.funding import FundingSourceInput
from app.api.routes.expense.model import (
    FamilyExpense,
    FamilyExpenseCategory,
    FamilyExpenseLog,
    PersonalExpense,
    PersonalExpenseLog,
)
from app.api.routes.family.model import LogFundingSource
from app.api.schemas.pagination import PaginationParams
from app.config import feature_settings
from app.core.constants import LEDGER_OUT, LEDGER_SOURCE_EXPENSE_LOG
from app.core.funding_sources import (
    assert_user_can_fund_from,
    pool_ref_from_funding_source,
    validate_funding_source_total,
)
from app.core.savings_ledger_service import SavingsLedgerService
from app.core.scope import ScopeContext, filter_entity_rows, load_scope_context

logger = logging.getLogger(__name__)


class ExpenseService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_categories(self, family_id: UUID) -> list[FamilyExpenseCategory]:
        stmt = (
            select(FamilyExpenseCategory)
            .where(FamilyExpenseCategory.family_id == family_id)
            .order_by(FamilyExpenseCategory.category_name.asc())
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def create_category(
        self, family_id: UUID, request: ExpenseCategoryCreateRequest
    ) -> FamilyExpenseCategory:
        cat = FamilyExpenseCategory(
            family_id=family_id,
            category_name=request.category_name,
        )
        self.pg_session.add(cat)
        await self.pg_session.commit()
        await self.pg_session.refresh(cat)
        return cat

    async def list_logs(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[object, bool]], int]:
        family_stmt = select(FamilyExpenseLog).where(
            FamilyExpenseLog.family_id == family_id
        )
        personal_stmt = select(PersonalExpenseLog).where(
            PersonalExpenseLog.family_id == family_id
        )
        family_logs = list((await self.pg_session.execute(family_stmt)).scalars().all())
        personal_logs = list((await self.pg_session.execute(personal_stmt)).scalars().all())
        combined: list[tuple[object, bool]] = [(l, False) for l in family_logs] + [
            (l, True) for l in personal_logs
        ]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].expense_date, reverse=True)
        total = len(combined)
        page = combined[pagination.offset : pagination.offset + pagination.page_size]
        return page, total

    async def create_log(
        self,
        family_id: UUID,
        logged_by: UUID,
        request: ExpenseLogCreateRequest,
    ) -> tuple[FamilyExpenseLog | PersonalExpenseLog, bool]:
        ledger = SavingsLedgerService(self.pg_session)
        spender = request.logged_by or logged_by
        if request.is_personal:
            if feature_settings.OWNERSHIP_STRICT:
                pass  # personal logs are always for caller
            log = PersonalExpenseLog(
                family_id=family_id,
                user_id=spender,
                scope_type=request.scope_type,
                logged_by=spender,
                expense_name=request.expense_name,
                amount=request.amount,
                category_id=request.category_id,
                expense_date=request.expense_date,
                source_type="MANUAL",
                access_level=request.access_level or "PRIVATE",
                expense_made_for_user_id=request.expense_made_for_user_id,
            )
            self.pg_session.add(log)
            await self.pg_session.flush()
            await self._apply_log_funding_sources(
                logged_by=spender,
                amount=request.amount,
                entity_type="PERSONAL_EXPENSE_LOG",
                entity_id=log.id,
                funding_sources=request.funding_sources,
                ledger=ledger,
            )
            await self.pg_session.commit()
            await self.pg_session.refresh(log)
            return log, True

        log = FamilyExpenseLog(
            family_id=family_id,
            scope_type=request.scope_type,
            logged_by=spender,
            expense_name=request.expense_name,
            amount=request.amount,
            category_id=request.category_id,
            expense_date=request.expense_date,
            source_type="MANUAL",
            access_level=request.access_level or "FAMILY",
            added_by_user_id=logged_by,
            expense_made_for_user_id=request.expense_made_for_user_id,
        )
        self.pg_session.add(log)
        await self.pg_session.flush()
        await self._apply_log_funding_sources(
            logged_by=spender,
            amount=request.amount,
            entity_type="FAMILY_EXPENSE_LOG",
            entity_id=log.id,
            funding_sources=request.funding_sources,
            ledger=ledger,
        )
        await self.pg_session.commit()
        await self.pg_session.refresh(log)
        return log, False

    async def _apply_log_funding_sources(
        self,
        *,
        logged_by: UUID,
        amount: Decimal,
        entity_type: str,
        entity_id: UUID,
        funding_sources: list[FundingSourceInput] | None,
        ledger: SavingsLedgerService,
    ) -> None:
        if not funding_sources:
            return

        validate_funding_source_total(amount, funding_sources)
        for source in funding_sources:
            await assert_user_can_fund_from(self.pg_session, logged_by, source)
            pool = pool_ref_from_funding_source(logged_by, source)
            source_row = await ledger._get_or_create_pool_row(pool)
            if source_row.total_savings < source.amount:
                raise ValueError("Insufficient balance in funding source")

        for source in funding_sources:
            pool = pool_ref_from_funding_source(logged_by, source)
            await ledger.apply_movement(
                pool=pool,
                amount=source.amount,
                direction=LEDGER_OUT,
                source_type=LEDGER_SOURCE_EXPENSE_LOG,
                source_id=entity_id,
            )
            self.pg_session.add(
                LogFundingSource(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    direction=LEDGER_OUT,
                    pool_type=source.pool_type,
                    family_id=source.family_id,
                    user_id=source.user_id,
                    amount=source.amount,
                )
            )

    async def get_log(
        self, log_id: UUID, family_id: UUID
    ) -> tuple[FamilyExpenseLog | PersonalExpenseLog, bool] | None:
        for model, is_personal in (
            (FamilyExpenseLog, False),
            (PersonalExpenseLog, True),
        ):
            stmt = select(model).where(model.id == log_id, model.family_id == family_id)
            row = (await self.pg_session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return row, is_personal
        return None

    async def update_log(
        self,
        log: FamilyExpenseLog | PersonalExpenseLog,
        is_personal: bool,
        user_id: UUID,
        request: ExpenseLogUpdateRequest,
    ) -> FamilyExpenseLog | PersonalExpenseLog:
        if log.logged_by != user_id:
            raise PermissionError("Only the user who logged this expense may edit it")

        for field, value in request.model_dump(exclude_none=True).items():
            setattr(log, field, value)

        await self.pg_session.commit()
        await self.pg_session.refresh(log)
        return log

    async def delete_log(
        self,
        log: FamilyExpenseLog | PersonalExpenseLog,
        user_id: UUID,
        *,
        is_manager: bool,
    ) -> None:
        if log.logged_by != user_id and not is_manager:
            raise PermissionError("Only the logger or a family manager may delete")
        await self.pg_session.delete(log)
        await self.pg_session.commit()

    async def list_recurring(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[object, bool]], int]:
        family_stmt = select(FamilyExpense).where(
            FamilyExpense.family_id == family_id,
            FamilyExpense.is_recurring.is_(True),
        )
        personal_stmt = select(PersonalExpense).where(
            PersonalExpense.family_id == family_id,
            PersonalExpense.is_recurring.is_(True),
        )
        family_rows = list((await self.pg_session.execute(family_stmt)).scalars().all())
        personal_rows = list((await self.pg_session.execute(personal_stmt)).scalars().all())
        combined: list[tuple[object, bool]] = [(e, False) for e in family_rows] + [
            (e, True) for e in personal_rows
        ]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].created_at, reverse=True)
        total = len(combined)
        page = combined[pagination.offset : pagination.offset + pagination.page_size]
        return page, total

    async def create_recurring(
        self,
        family_id: UUID,
        user_id: UUID,
        request: ExpenseRecurringCreateRequest,
    ) -> tuple[FamilyExpense | PersonalExpense, bool]:
        spender = request.logged_by or user_id
        if request.is_personal:
            expense = PersonalExpense(
                family_id=family_id,
                user_id=spender,
                scope_type=request.scope_type,
                expense_name=request.expense_name,
                amount=request.amount,
                category_id=request.category_id,
                is_recurring=True,
                paid_every=request.paid_every,
                next_payment_date=request.next_payment_date,
                access_level=request.access_level or "PRIVATE",
                expense_made_for_user_id=request.expense_made_for_user_id,
            )
            self.pg_session.add(expense)
            await self.pg_session.commit()
            await self.pg_session.refresh(expense)
            return expense, True

        expense = FamilyExpense(
            family_id=family_id,
            scope_type=request.scope_type,
            expense_name=request.expense_name,
            amount=request.amount,
            category_id=request.category_id,
            is_recurring=True,
            paid_every=request.paid_every,
            next_payment_date=request.next_payment_date,
            access_level=request.access_level or "FAMILY",
            added_by_user_id=user_id,
            expense_made_for_user_id=request.expense_made_for_user_id,
        )
        self.pg_session.add(expense)
        await self.pg_session.commit()
        await self.pg_session.refresh(expense)
        return expense, False

    async def get_recurring(
        self, expense_id: UUID, family_id: UUID
    ) -> tuple[FamilyExpense | PersonalExpense, bool] | None:
        for model, is_personal in ((FamilyExpense, False), (PersonalExpense, True)):
            stmt = select(model).where(
                model.id == expense_id,
                model.family_id == family_id,
                model.is_recurring.is_(True),
            )
            row = (await self.pg_session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return row, is_personal
        return None

    async def update_recurring(
        self,
        expense: FamilyExpense | PersonalExpense,
        request: ExpenseRecurringUpdateRequest,
    ) -> FamilyExpense | PersonalExpense:
        for field, value in request.model_dump(exclude_none=True).items():
            if field == "logged_by" and isinstance(expense, PersonalExpense):
                expense.user_id = value
            else:
                setattr(expense, field, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(expense)
        return expense

    async def delete_recurring(self, expense: FamilyExpense | PersonalExpense) -> None:
        await self.pg_session.delete(expense)
        await self.pg_session.commit()

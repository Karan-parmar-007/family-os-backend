import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.document.document_service import DocumentService
from app.api.routes.family_expense.expense_schemas import (
    FamilyExpenseLogCreateRequest,
    FamilyExpenseLogUpdateRequest,
    FamilyExpenseLogListItem,
    PersonalExpenseLogCreateRequest,
    PersonalExpenseLogListItem,
    PersonalExpenseLogUpdateRequest,
    RecurringExpenseCreateRequest,
    RecurringExpenseQuickAddRequest,
    RecurringExpenseUpdateRequest,
    RecurringExpenseDetail,
    RecurringExpenseFamilySplitDetail,
    FamilyRecurringExpenseSummary,
    FamilySplitInput,
    _validate_expense_splits,
    _validate_expense_recurrence,
)
from app.api.routes.family_expense.model import (
    RecurringExpense,
    RecurringExpenseFamilySplit,
    RecurringExpenseDocAccess,
    FamilyExpenseLogDocAccess,
)
from app.api.routes.expense.model import (
    FamilyExpenseCategory,
    FamilyExpenseLog,
    PersonalExpenseLog,
)
from app.api.routes.family.model import Family, LogFundingSource
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.funding import FundingSourceInput
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_EXPENSE_LOG,
    POOL_FAMILY,
    POOL_PERSONAL,
)
from app.core.funding_sources import (
    assert_user_can_fund_from,
    pool_ref_from_funding_source,
    summarize_personal_funding,
    validate_log_funding_sources,
)
from app.core.split_log_helpers import (
    create_linked_expense_logs,
    fetch_log_funding_sources,
    is_other_family_source,
    remove_linked_expense_logs,
    replace_primary_log_funding,
    resolve_let_everyone_edit,
)
from app.core.log_breakdown_helpers import (
    ENTITY_FAMILY_EXPENSE_LOG,
    log_ids_with_breakdown,
    sync_log_funding_breakdown,
)
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.scope import ScopeContext, can_view_expense_log, can_view_scoped_entity
from app.api.routes.user.model import UserBase
from app.api.schemas.pagination import PaginationParams

logger = logging.getLogger(__name__)


class RecurringExpenseService:
    def __init__(self, pg_session: AsyncSession, garage_client: Any):
        self.pg_session = pg_session
        self.garage_client = garage_client
        self._document_service = DocumentService(pg_session, garage_client)

    async def get_default_category_id(self, family_id: UUID) -> UUID:
        stmt = select(FamilyExpenseCategory).where(
            FamilyExpenseCategory.family_id == family_id,
            FamilyExpenseCategory.category_name == "Other",
        )
        cat = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if cat is not None:
            return cat.id
        import uuid6

        cat = FamilyExpenseCategory(
            id=uuid6.uuid7(),
            family_id=family_id,
            category_name="Other",
        )
        self.pg_session.add(cat)
        await self.pg_session.flush()
        return cat.id

    # ------------------------------------------------------------------
    # Recurring expense queries
    # ------------------------------------------------------------------

    async def _assert_user_in_families(
        self, user_id: UUID, family_ids: list[UUID]
    ) -> None:
        if not family_ids:
            return
        stmt = select(UserFamilyLink.family_id).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id.in_(family_ids),
        )
        found = set((await self.pg_session.execute(stmt)).scalars().all())
        missing = [fid for fid in family_ids if fid not in found]
        if missing:
            raise ValueError("You are not a member of one or more selected families")

    async def _get_splits_for_expense(
        self, expense_id: UUID
    ) -> list[RecurringExpenseFamilySplit]:
        stmt = select(RecurringExpenseFamilySplit).where(
            RecurringExpenseFamilySplit.expense_id == expense_id
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def _build_recurring_detail(
        self,
        expense: RecurringExpense,
        *,
        viewer_user_id: UUID | None = None,
        family_id: UUID | None = None,
    ) -> RecurringExpenseDetail:
        splits = await self._get_splits_for_expense(expense.id)
        family_names: dict[UUID, str] = {}
        if splits:
            fam_stmt = select(Family).where(
                Family.id.in_([s.family_id for s in splits])
            )
            for fam in (await self.pg_session.execute(fam_stmt)).scalars().all():
                family_names[fam.id] = fam.name

        viewer_ids = await self._get_recurring_expense_doc_viewers(expense.id)
        detail = RecurringExpenseDetail.model_validate(expense)
        detail.doc_viewer_user_ids = viewer_ids
        detail.family_splits = [
            RecurringExpenseFamilySplitDetail(
                family_id=s.family_id,
                family_name=family_names.get(s.family_id),
                split_name=s.split_name,
                amount=s.amount,
            )
            for s in splits
        ]
        from app.api.routes.family_expense.model import RecurringExpensePersonalSplit
        from app.api.routes.family_expense.expense_schemas import (
            RecurringExpensePersonalSplitDetail,
        )

        personal_rows = list(
            (
                await self.pg_session.execute(
                    select(RecurringExpensePersonalSplit).where(
                        RecurringExpensePersonalSplit.expense_id == expense.id
                    )
                )
            ).scalars().all()
        )
        detail.personal_splits = [
            RecurringExpensePersonalSplitDetail(user_id=r.user_id, amount=r.amount)
            for r in personal_rows
        ]
        if viewer_user_id is not None:
            detail.can_edit = await self.can_edit_recurring_expense(
                viewer_user_id, expense, family_id=family_id
            )
        return detail

    async def can_edit_recurring_expense(
        self,
        user_id: UUID,
        expense: RecurringExpense,
        *,
        family_id: UUID | None = None,
    ) -> bool:
        if expense.user_id == user_id:
            return True
        if not expense.is_family_managed or not expense.let_everyone_edit:
            return False
        if family_id is None:
            return False
        splits = await self._get_splits_for_expense(expense.id)
        if not any(s.family_id == family_id for s in splits):
            return False
        try:
            await self._assert_user_in_families(user_id, [family_id])
        except ValueError:
            return False
        return True

    async def list_user_recurring_expenses(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        personal_only: bool = False,
    ) -> tuple[list[RecurringExpenseDetail], int]:
        filters: list[Any] = [RecurringExpense.user_id == user_id]
        if personal_only:
            filters.append(RecurringExpense.is_family_managed.is_(False))
        count_stmt = (
            select(func.count()).select_from(RecurringExpense).where(*filters)
        )
        total_count = (await self.pg_session.execute(count_stmt)).scalar_one()

        stmt = (
            select(RecurringExpense)
            .where(*filters)
            .order_by(RecurringExpense.created_at.desc())  # type: ignore[attr-defined]
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        expenses = list((await self.pg_session.execute(stmt)).scalars().all())
        items = [
            await self._build_recurring_detail(inc, viewer_user_id=user_id)
            for inc in expenses
        ]
        return items, total_count

    async def list_my_family_managed_recurring_expenses(
        self,
        user_id: UUID,
        family_id: UUID,
        pagination: PaginationParams,
    ) -> tuple[list[RecurringExpenseDetail], int]:
        """Current user's family-managed recurring expenses with a split in this family."""
        stmt = (
            select(RecurringExpense)
            .join(
                RecurringExpenseFamilySplit,
                RecurringExpenseFamilySplit.expense_id == RecurringExpense.id,
            )
            .where(
                RecurringExpenseFamilySplit.family_id == family_id,
                RecurringExpense.is_family_managed.is_(True),
                RecurringExpense.user_id == user_id,
            )
            .order_by(RecurringExpense.created_at.desc())  # type: ignore[attr-defined]
        )
        rows = list((await self.pg_session.execute(stmt)).scalars().all())
        seen: set[UUID] = set()
        expenses: list[RecurringExpense] = []
        for inc in rows:
            if inc.id in seen:
                continue
            seen.add(inc.id)
            expenses.append(inc)

        total_count = len(expenses)
        page = expenses[pagination.offset : pagination.offset + pagination.page_size]
        items = [
            await self._build_recurring_detail(
                inc, viewer_user_id=user_id, family_id=family_id
            )
            for inc in page
        ]
        return items, total_count

    async def list_family_recurring_expense_splits(
        self,
        family_id: UUID,
        pagination: PaginationParams,
    ) -> tuple[list[FamilyRecurringExpenseSummary], int]:
        stmt = (
            select(RecurringExpenseFamilySplit, RecurringExpense)
            .join(RecurringExpense, RecurringExpense.id == RecurringExpenseFamilySplit.expense_id)
            .where(RecurringExpenseFamilySplit.family_id == family_id)
            .order_by(RecurringExpense.created_at.desc())  # type: ignore[attr-defined]
        )
        rows = list((await self.pg_session.execute(stmt)).all())
        items = [
            FamilyRecurringExpenseSummary(
                id=split.id,
                recurring_expense_id=expense.id,
                split_name=split.split_name,
                amount=split.amount,
                paid_every=expense.paid_every,
                repeat_interval_days=expense.repeat_interval_days,
                repeat_interval_months=expense.repeat_interval_months,
                repeat_interval_years=expense.repeat_interval_years,
                next_payment_date=expense.next_payment_date,
                paid_by_user_id=expense.user_id,
            )
            for split, expense in rows
        ]
        total_count = len(items)
        page = items[pagination.offset : pagination.offset + pagination.page_size]
        return page, total_count

    # ------------------------------------------------------------------
    # Recurring expense mutations
    # ------------------------------------------------------------------

    async def _sync_family_splits(
        self,
        expense_id: UUID,
        splits: list[FamilySplitInput],
    ) -> None:
        await self.pg_session.execute(
            delete(RecurringExpenseFamilySplit).where(
                RecurringExpenseFamilySplit.expense_id == expense_id
            )
        )
        await self.pg_session.flush()
        for split in splits:
            self.pg_session.add(
                RecurringExpenseFamilySplit(
                    expense_id=expense_id,
                    family_id=split.family_id,
                    split_name=split.split_name,
                    amount=split.amount,
                )
            )
        await self.pg_session.flush()

    async def _sync_personal_splits(
        self,
        expense_id: UUID,
        *,
        owner_user_id: UUID,
        personal_amount: Decimal | None,
        personal_splits: list | None = None,
    ) -> None:
        from app.api.routes.family_expense.model import RecurringExpensePersonalSplit
        from app.api.routes.friend.friend_service import FriendService

        await self.pg_session.execute(
            delete(RecurringExpensePersonalSplit).where(
                RecurringExpensePersonalSplit.expense_id == expense_id
            )
        )
        await self.pg_session.flush()

        resolved = list(personal_splits or [])
        if not resolved and personal_amount and personal_amount > 0:
            resolved = [{"user_id": owner_user_id, "amount": personal_amount}]

        friend_service = FriendService(self.pg_session)
        for split in resolved:
            user_id = split.user_id if hasattr(split, "user_id") else split["user_id"]
            amount = split.amount if hasattr(split, "amount") else split["amount"]
            await friend_service.assert_can_allocate_to_personal(owner_user_id, user_id)
            self.pg_session.add(
                RecurringExpensePersonalSplit(
                    expense_id=expense_id,
                    user_id=user_id,
                    amount=amount,
                )
            )
        await self.pg_session.flush()

    async def create_recurring_expense(
        self,
        user_id: UUID,
        data: RecurringExpenseCreateRequest,
        document: UploadFile | None = None,
        *,
        document_family_id: UUID | None = None,
        is_family_managed: bool = False,
        let_everyone_edit: bool = False,
    ) -> RecurringExpense:
        await self._assert_user_in_families(
            user_id, [s.family_id for s in data.family_splits]
        )

        document_id: UUID | None = None
        if document is not None and document.filename:
            store_family = document_family_id or (
                data.family_splits[0].family_id if data.family_splits else None
            )
            if store_family is None:
                raise ValueError("A family context is required to upload a document")
            stored_document = await self._document_service.store_family_document(
                family_id=store_family,
                file=document,
            )
            document_id = stored_document.id

        category_id = data.category_id
        if not category_id:
            family_id = None
            if data.family_splits:
                family_id = data.family_splits[0].family_id
            else:
                stmt_fam = select(UserFamilyLink.family_id).where(
                    UserFamilyLink.user_id == user_id
                )
                family_id = (await self.pg_session.execute(stmt_fam)).scalars().first()
            if family_id:
                category_id = await self.get_default_category_id(family_id)

        personal = data.personal_savings_amount if data.personal_savings_amount else None
        expense = RecurringExpense(
            user_id=user_id,
            expense_name=data.expense_name,
            total_amount=data.total_amount,
            personal_savings_amount=personal,
            paid_every=data.paid_every,
            repeat_interval_days=data.repeat_interval_days,
            repeat_interval_months=data.repeat_interval_months,
            repeat_interval_years=data.repeat_interval_years,
            next_payment_date=data.next_payment_date,
            document_id=document_id,
            show_docs_to_all=data.show_docs_to_all,
            repeat_doc_with_logs=data.repeat_doc_with_logs,
            is_family_managed=is_family_managed,
            let_everyone_edit=let_everyone_edit if is_family_managed else False,
            category_id=category_id,
        )
        self.pg_session.add(expense)
        await self.pg_session.flush()

        if data.family_splits:
            await self._sync_family_splits(expense.id, data.family_splits)

        await self._sync_personal_splits(
            expense.id,
            owner_user_id=user_id,
            personal_amount=personal,
            personal_splits=getattr(data, "personal_splits", None),
        )

        if not data.show_docs_to_all and data.doc_viewer_user_ids:
            await self._sync_recurring_expense_doc_access(expense.id, data.doc_viewer_user_ids)

        from app.scheduler.expense_cron import create_or_replace_next_job

        await create_or_replace_next_job(self.pg_session, expense)
        await self.pg_session.commit()
        await self.pg_session.refresh(expense)
        return expense

    async def quick_add_recurring_expense(
        self,
        user_id: UUID,
        family_id: UUID,
        data: RecurringExpenseQuickAddRequest,
        document: UploadFile | None = None,
    ) -> RecurringExpense:
        family_amount = data.family_amount
        personal = data.personal_savings_amount
        personal_splits = list(getattr(data, "personal_splits", None) or [])
        if personal_splits:
            personal = sum((s.amount for s in personal_splits), Decimal("0"))
            if family_amount is None:
                family_amount = data.total_amount - personal
        if family_amount is None and personal is None:
            family_amount = data.total_amount
            personal = Decimal("0")
        else:
            family_amount = family_amount or Decimal("0")
            personal = personal or Decimal("0")
        splits: list[FamilySplitInput] = []
        if family_amount > 0:
            splits.append(
                FamilySplitInput(
                    family_id=family_id,
                    split_name=data.split_name or data.expense_name,
                    amount=family_amount,
                )
            )
        create_data = RecurringExpenseCreateRequest(
            expense_name=data.expense_name,
            total_amount=data.total_amount,
            personal_savings_amount=personal if personal > 0 else None,
            personal_splits=personal_splits,
            family_splits=splits,
            paid_every=data.paid_every,
            repeat_interval_days=data.repeat_interval_days,
            repeat_interval_months=data.repeat_interval_months,
            repeat_interval_years=data.repeat_interval_years,
            next_payment_date=data.next_payment_date,
            show_docs_to_all=data.show_docs_to_all,
            repeat_doc_with_logs=data.repeat_doc_with_logs,
            doc_viewer_user_ids=data.doc_viewer_user_ids,
            category_id=data.category_id,
        )
        return await self.create_recurring_expense(
            user_id,
            create_data,
            document,
            document_family_id=family_id,
            is_family_managed=True,
            let_everyone_edit=data.let_everyone_edit,
        )

    async def update_recurring_expense(
        self,
        expense: RecurringExpense,
        data: RecurringExpenseUpdateRequest,
        document: UploadFile | None = None,
        *,
        document_family_id: UUID | None = None,
    ) -> RecurringExpense:
        if document is not None and document.filename:
            store_family = document_family_id
            if store_family is None:
                splits = await self._get_splits_for_expense(expense.id)
                store_family = splits[0].family_id if splits else None
            if store_family is None:
                raise ValueError("Cannot replace document without a family context")
            old_document_id = expense.document_id
            if old_document_id is not None:
                expense.document_id = None
                await self.pg_session.flush()
            stored_document = await self._document_service.replace_family_document(
                family_id=store_family,
                file=document,
                old_document_id=old_document_id,
            )
            expense.document_id = stored_document.id

        recurrence_fields = {
            "paid_every",
            "repeat_interval_days",
            "repeat_interval_months",
            "repeat_interval_years",
            "next_payment_date",
        }
        update_data = data.model_dump(exclude={"doc_viewer_user_ids", "family_splits", "personal_splits"})
        for field, value in update_data.items():
            if field in recurrence_fields:
                continue
            if value is not None:
                setattr(expense, field, value)

        if data.next_payment_date is not None:
            expense.paid_every = data.paid_every
            expense.repeat_interval_days = data.repeat_interval_days
            expense.repeat_interval_months = data.repeat_interval_months
            expense.repeat_interval_years = data.repeat_interval_years
            expense.next_payment_date = data.next_payment_date

        if data.family_splits is not None:
            await self._assert_user_in_families(
                expense.user_id, [s.family_id for s in data.family_splits]
            )
            await self._sync_family_splits(expense.id, data.family_splits)

        if data.personal_splits is not None:
            personal_sum = sum((s.amount for s in data.personal_splits), Decimal("0"))
            expense.personal_savings_amount = personal_sum if personal_sum > 0 else None
            await self._sync_personal_splits(
                expense.id,
                owner_user_id=expense.user_id,
                personal_amount=expense.personal_savings_amount,
                personal_splits=data.personal_splits,
            )
        elif data.personal_savings_amount is not None:
            await self._sync_personal_splits(
                expense.id,
                owner_user_id=expense.user_id,
                personal_amount=data.personal_savings_amount,
                personal_splits=None,
            )

        splits = await self._get_splits_for_expense(expense.id)
        _validate_expense_splits(
            expense.total_amount,
            expense.personal_savings_amount,
            [
                FamilySplitInput(
                    family_id=s.family_id, split_name=s.split_name, amount=s.amount
                )
                for s in splits
            ],
        )
        _validate_expense_recurrence(
            expense.paid_every,
            expense.repeat_interval_days,
            expense.repeat_interval_months,
            expense.repeat_interval_years,
        )
        if expense.next_payment_date is None:
            raise ValueError("next_payment_date is required")

        if data.doc_viewer_user_ids is not None:
            await self._sync_recurring_expense_doc_access(expense.id, data.doc_viewer_user_ids)

        if data.let_everyone_edit is not None:
            if not expense.is_family_managed:
                raise ValueError("let_everyone_edit applies only to family recurring expense")
            expense.let_everyone_edit = data.let_everyone_edit

        from app.scheduler.expense_cron import create_or_replace_next_job

        await create_or_replace_next_job(self.pg_session, expense)
        await self.pg_session.commit()
        await self.pg_session.refresh(expense)
        return expense

    async def cancel_recurring_expense(self, expense: RecurringExpense) -> RecurringExpense:
        expense.next_payment_date = None
        from app.scheduler.expense_cron import cancel_pending_expense_jobs

        await cancel_pending_expense_jobs(self.pg_session, expense.id)
        await self.pg_session.commit()
        await self.pg_session.refresh(expense)
        return expense

    # Legacy aliases
    async def list_family_recurring_expenses_added_by_user(self, *args, **kwargs):
        return await self.list_user_recurring_expenses(*args, **kwargs)

    async def list_family_recurring_expenses(self, family_id, pagination, **kwargs):
        return await self.list_family_recurring_expense_splits(family_id, pagination)

    async def create_family_recurring_expense(self, family_id, added_by_user_id, data, document=None):
        raise NotImplementedError("Use quick_add_recurring_expense or create_recurring_expense")

    async def update_family_recurring_expense(self, *args, **kwargs):
        raise NotImplementedError("Use update_recurring_expense from personal routes")

    async def cancel_family_recurring_expense(self, expense):
        return await self.cancel_recurring_expense(expense)

    # ------------------------------------------------------------------
    # Expense log queries
    # ------------------------------------------------------------------

    async def list_family_expense_logs(
        self,
        family_id: UUID,
        current_user_id: UUID,
        pagination: PaginationParams,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        logged_by_user_id: UUID | None = None,
        category_id: UUID | None = None,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[FamilyExpenseLogListItem], int]:
        """Fetch a paginated list of family expense logs with optional filters."""
        filters = [FamilyExpenseLog.family_id == family_id]
        if start_date is not None:
            filters.append(FamilyExpenseLog.expense_date >= start_date)
        if end_date is not None:
            filters.append(FamilyExpenseLog.expense_date <= end_date)
        if logged_by_user_id is not None:
            filters.append(FamilyExpenseLog.logged_by == logged_by_user_id)
        if category_id is not None:
            filters.append(FamilyExpenseLog.category_id == category_id)

        stmt = (
            select(FamilyExpenseLog, UserBase.name, FamilyExpenseCategory.category_name)
            .outerjoin(
                UserBase,
                FamilyExpenseLog.logged_by == UserBase.id,
            )
            .outerjoin(
                FamilyExpenseCategory,
                FamilyExpenseLog.category_id == FamilyExpenseCategory.id,
            )
            .where(*filters)
            .order_by(FamilyExpenseLog.expense_date.desc())  # type: ignore[attr-defined]
        )
        result = await self.pg_session.execute(stmt)
        rows = result.all()

        if scope_ctx is not None:
            rows = [(log, name, cat_name) for log, name, cat_name in rows if can_view_expense_log(scope_ctx, log)]

        total_count = len(rows)
        rows = rows[pagination.offset : pagination.offset + pagination.page_size]

        breakdown_ids = await log_ids_with_breakdown(
            self.pg_session,
            ENTITY_FAMILY_EXPENSE_LOG,
            [log.id for log, _, _ in rows],
        )

        items: list[FamilyExpenseLogListItem] = []
        for log, logger_name, category_name in rows:
            viewer_ids = await self._get_expense_log_doc_viewers(log.id)
            display_total = log.total_amount or log.amount
            items.append(
                FamilyExpenseLogListItem(
                    id=log.id,
                    expense_name=log.expense_name,
                    source_type=log.source_type,
                    expense_date=log.expense_date,
                    added_by_user_id=log.added_by_user_id or log.logged_by,
                    total_amount=display_total,
                    family_amount=log.family_amount,
                    personal_savings_amount=log.personal_savings_amount,
                    personal_savings_user_id=log.personal_savings_user_id,
                    logged_by_user_name=logger_name,
                    logged_by_user_id=log.logged_by,
                    document_id=log.document_id,
                    show_doc_to_all=log.show_doc_to_all,
                    doc_viewer_user_ids=viewer_ids,
                    can_edit=(
                        ((log.added_by_user_id or log.logged_by) == current_user_id)
                        or log.let_everyone_edit
                    ),
                    let_everyone_edit=log.let_everyone_edit,
                    has_breakdown=log.id in breakdown_ids,
                    category_id=log.category_id,
                    category_name=category_name,
                    expense_made_for_user_id=log.expense_made_for_user_id,
                )
            )

        return items, total_count

    async def list_personal_expense_logs(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        category_id: UUID | None = None,
    ) -> tuple[list[PersonalExpenseLogListItem], int]:
        """List personal expense logs where the user paid from personal savings."""
        filters = [PersonalExpenseLog.user_id == user_id]
        if start_date is not None:
            filters.append(PersonalExpenseLog.expense_date >= start_date)
        if end_date is not None:
            filters.append(PersonalExpenseLog.expense_date <= end_date)
        if category_id is not None:
            filters.append(PersonalExpenseLog.category_id == category_id)

        stmt = (
            select(PersonalExpenseLog, Family.name, FamilyExpenseCategory.category_name)
            .outerjoin(Family, PersonalExpenseLog.family_id == Family.id)
            .outerjoin(
                FamilyExpenseCategory,
                PersonalExpenseLog.category_id == FamilyExpenseCategory.id,
            )
            .where(*filters)
            .order_by(PersonalExpenseLog.expense_date.desc())  # type: ignore[attr-defined]
        )
        rows = (await self.pg_session.execute(stmt)).all()
        total_count = len(rows)
        rows = rows[pagination.offset : pagination.offset + pagination.page_size]

        items: list[PersonalExpenseLogListItem] = []
        for log, family_name, category_name in rows:
            items.append(
                PersonalExpenseLogListItem(
                    id=log.id,
                    expense_name=log.expense_name,
                    amount=log.amount,
                    expense_date=log.expense_date,
                    source_type=log.source_type,
                    family_id=log.family_id,
                    family_name=family_name,
                    family_expense_log_id=log.family_expense_log_id,
                    document_id=log.document_id,
                    show_doc_to_all=log.show_doc_to_all,
                    can_edit=log.source_type == "MANUAL" and log.logged_by == user_id,
                    category_id=log.category_id,
                    category_name=category_name,
                )
            )
        return items, total_count

    async def get_personal_expense_log_detail(
        self,
        log_id: UUID,
        user_id: UUID,
    ) -> PersonalExpenseLog | None:
        stmt = select(PersonalExpenseLog).where(
            PersonalExpenseLog.id == log_id,
            PersonalExpenseLog.user_id == user_id,
        )
        return (await self.pg_session.execute(stmt)).scalar_one_or_none()

    async def create_personal_expense_log(
        self,
        user_id: UUID,
        data: PersonalExpenseLogCreateRequest,
        document: UploadFile | None = None,
    ) -> tuple[PersonalExpenseLog, Decimal]:
        document_id: UUID | None = None
        stored_document = None
        if document is not None and document.filename:
            try:
                stored_document = await self._document_service.store_user_document(
                    user_id=user_id,
                    file=document,
                )
                document_id = stored_document.id
            except Exception as e:
                logger.error("Failed to store user document: %s", e)
                raise ValueError("Failed to upload supporting document") from e

        try:
            category_id = data.category_id
            if not category_id:
                stmt_fam = select(UserFamilyLink.family_id).where(
                    UserFamilyLink.user_id == user_id
                )
                family_id = (await self.pg_session.execute(stmt_fam)).scalars().first()
                if family_id:
                    category_id = await self.get_default_category_id(family_id)

            log = PersonalExpenseLog(
                family_id=None,
                user_id=user_id,
                logged_by=user_id,
                expense_name=data.expense_name,
                amount=data.amount,
                expense_date=data.expense_date,
                source_type="MANUAL",
                document_id=document_id,
                show_doc_to_all=data.show_doc_to_all,
                category_id=category_id,
            )
            self.pg_session.add(log)
            await self.pg_session.flush()

            ledger = SavingsLedgerService(self.pg_session)
            await ledger.apply_movement(
                SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user_id),
                data.amount,
                LEDGER_OUT,
                LEDGER_SOURCE_EXPENSE_LOG,
                source_id=log.id,
                occurred_at=data.expense_date,
            )

            await self.pg_session.commit()
            await self.pg_session.refresh(log)
        except Exception as exc:
            await self.pg_session.rollback()
            if stored_document is not None and stored_document.file_path:
                try:
                    from app.config import db_settings
                    await self.garage_client.delete_object(
                        Bucket=db_settings.GARAGE_BUCKET_NAME,
                        Key=stored_document.file_path,
                    )
                except Exception as e:
                    logger.error("Failed to delete rolled-back document from Garage: %s", e)
            raise exc

        return log, data.amount

    async def update_personal_expense_log(
        self,
        log_id: UUID,
        user_id: UUID,
        data: PersonalExpenseLogUpdateRequest,
        document: UploadFile | None = None,
    ) -> tuple[PersonalExpenseLog, Decimal]:
        log = await self.get_personal_expense_log_detail(log_id, user_id)
        if log is None:
            raise ValueError("Expense log not found")
        if log.source_type != "MANUAL":
            raise PermissionError("Only manually added personal expense logs can be edited here")
        if log.logged_by != user_id:
            raise PermissionError("Only the user who added this log may edit it")

        original_amount = log.amount
        stored_document = None
        if document is not None and document.filename:
            try:
                if log.document_id is not None:
                    try:
                        old_doc = await self._document_service.get_document(log.document_id)
                        if self._document_service.user_owns_document(user_id, old_doc):
                            await self._document_service.delete_document(log.document_id)
                    except Exception:
                        pass
                stored_document = await self._document_service.store_user_document(
                    user_id=user_id,
                    file=document,
                )
                log.document_id = stored_document.id
            except Exception as e:
                logger.error("Failed to store user document: %s", e)
                raise ValueError("Failed to upload supporting document") from e

        if data.expense_name is not None:
            log.expense_name = data.expense_name
        if data.expense_date is not None:
            log.expense_date = data.expense_date
        if data.show_doc_to_all is not None:
            log.show_doc_to_all = data.show_doc_to_all
        if data.category_id is not None:
            log.category_id = data.category_id

        new_amount = data.amount if data.amount is not None else original_amount
        log.amount = new_amount

        try:
            if new_amount != original_amount:
                ledger = SavingsLedgerService(self.pg_session)
                if original_amount > 0:
                    await ledger.apply_movement(
                        SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user_id),
                        original_amount,
                        LEDGER_IN,
                        LEDGER_SOURCE_EXPENSE_LOG,
                        source_id=log.id,
                    )
                if new_amount > 0:
                    await ledger.apply_movement(
                        SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user_id),
                        new_amount,
                        LEDGER_OUT,
                        LEDGER_SOURCE_EXPENSE_LOG,
                        source_id=log.id,
                    )

            self.pg_session.add(log)
            await self.pg_session.commit()
            await self.pg_session.refresh(log)
        except Exception as exc:
            await self.pg_session.rollback()
            if stored_document is not None and stored_document.file_path:
                try:
                    from app.config import db_settings
                    await self.garage_client.delete_object(
                        Bucket=db_settings.GARAGE_BUCKET_NAME,
                        Key=stored_document.file_path,
                    )
                except Exception as e:
                    logger.error("Failed to delete rolled-back document from Garage: %s", e)
            raise exc

        return log, new_amount - original_amount

    async def get_family_expense_log_detail(
        self,
        log_id: UUID,
        family_id: UUID,
    ) -> FamilyExpenseLog | None:
        """Fetch full detail of a family expense log by ID."""
        stmt = select(FamilyExpenseLog).where(
            FamilyExpenseLog.id == log_id,
            FamilyExpenseLog.family_id == family_id,
        )
        result = await self.pg_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_family_expense_log_detail_with_access(
        self,
        log_id: UUID,
        family_id: UUID,
    ) -> tuple[FamilyExpenseLog, list[UUID]] | None:
        """Fetch full detail of a family expense log along with its doc viewer ids."""
        log = await self.get_family_expense_log_detail(log_id, family_id)
        if log is None:
            return None
        viewer_ids = await self._get_expense_log_doc_viewers(log_id)
        return log, viewer_ids

    # ------------------------------------------------------------------
    # Expense log mutations
    # ------------------------------------------------------------------

    async def create_family_expense_log(
        self,
        family_id: UUID,
        logged_by_user_id: UUID,
        data: FamilyExpenseLogCreateRequest,
        document: UploadFile | None = None,
    ) -> tuple[FamilyExpenseLog, Decimal, Decimal | None, UUID | None]:
        """Create a family expense log and update savings totals.

        family_amount and personal_savings_amount are optional.
        If neither (and no funding_sources) is provided, the full total debits
        this family's savings. If provided, they must sum to total_amount.

        Returns:
            Tuple of (expense_log, family_savings_updated, personal_savings_updated, personal_savings_user_id)
        """
        # Upload supporting document if provided
        document_id: UUID | None = None
        stored_document = None
        if document is not None and document.filename:
            try:
                stored_document = await self._document_service.store_family_document(
                    family_id=family_id,
                    file=document,
                )
                document_id = stored_document.id
            except Exception as e:
                logger.error("Failed to store family document: %s", e)
                raise ValueError("Failed to upload supporting document") from e

        # Spender defaults to the logging user; personal lines may target family/friends
        spender_user_id = data.logged_by or logged_by_user_id

        family_amount = data.family_amount
        personal_amount = data.personal_savings_amount
        funding_sources = data.funding_sources
        # Total only → 100% from this family's savings (same default as recurring quick-add)
        if funding_sources is None and family_amount is None and personal_amount is None:
            family_amount = data.total_amount
            personal_amount = None
        if funding_sources is None and (family_amount is not None or personal_amount is not None):
            funding_sources = []
            if family_amount is not None and family_amount > 0:
                funding_sources.append(
                    FundingSourceInput(
                        pool_type=POOL_FAMILY,
                        family_id=family_id,
                        amount=family_amount,
                    )
                )
            if personal_amount is not None and personal_amount > 0:
                personal_target = data.personal_savings_user_id or spender_user_id
                funding_sources.append(
                    FundingSourceInput(
                        pool_type=POOL_PERSONAL,
                        user_id=personal_target,
                        amount=personal_amount,
                    )
                )
        if funding_sources:
            normalized: list[FundingSourceInput] = []
            for source in funding_sources:
                if source.pool_type == POOL_PERSONAL and source.user_id is None:
                    normalized.append(
                        FundingSourceInput(
                            pool_type=POOL_PERSONAL,
                            user_id=data.personal_savings_user_id or spender_user_id,
                            amount=source.amount,
                        )
                    )
                else:
                    normalized.append(source)
            funding_sources = normalized
            validate_log_funding_sources(data.total_amount, funding_sources, family_id)
            for source in funding_sources:
                await assert_user_can_fund_from(
                    self.pg_session,
                    spender_user_id,
                    source,
                    primary_family_id=family_id,
                )
            family_amount = sum(
                (
                    source.amount
                    for source in funding_sources
                    if source.pool_type == POOL_FAMILY and source.family_id == family_id
                ),
                Decimal("0"),
            )
            personal_amount, target_user_id = summarize_personal_funding(
                funding_sources, actor_user_id=spender_user_id
            )
        else:
            target_user_id = (
                data.personal_savings_user_id or spender_user_id
                if personal_amount and personal_amount > 0
                else None
            )
        let_everyone = resolve_let_everyone_edit(
            data.let_everyone_edit,
            funding_sources,
            family_id,
            personal_amount,
        )

        try:
            new_log = FamilyExpenseLog(
                family_id=family_id,
                scope_type=data.scope_type,
                logged_by=spender_user_id,
                expense_name=data.expense_name,
                amount=data.total_amount,
                total_amount=data.total_amount,
                family_amount=family_amount,
                expense_date=data.expense_date,
                source_type="MANUAL",
                source_id=None,
                personal_savings_amount=personal_amount if personal_amount else None,
                personal_savings_user_id=target_user_id,
                document_id=document_id or data.document_id,
                added_by_user_id=logged_by_user_id,
                show_doc_to_all=data.show_doc_to_all,
                let_everyone_edit=let_everyone,
                show_funding_to_family=data.show_funding_to_family,
                category_id=data.category_id,
                expense_made_for_user_id=data.expense_made_for_user_id,
            )
            self.pg_session.add(new_log)
            await self.pg_session.flush()

            family_savings_updated = Decimal("0")
            personal_savings_updated: Decimal | None = None
            personal_savings_user_id: UUID | None = None

            ledger = SavingsLedgerService(self.pg_session)
            if funding_sources:
                for source in funding_sources:
                    pool = pool_ref_from_funding_source(spender_user_id, source)
                    source_row = await ledger._get_or_create_pool_row(pool)
                    if source_row.total_savings < source.amount:
                        raise ValueError("Insufficient balance in funding source")
                for source in funding_sources:
                    if is_other_family_source(source, family_id):
                        continue
                    pool = pool_ref_from_funding_source(spender_user_id, source)
                    await ledger.apply_movement(
                        pool,
                        source.amount,
                        LEDGER_OUT,
                        LEDGER_SOURCE_EXPENSE_LOG,
                        source_id=new_log.id,
                    )
                    self.pg_session.add(
                        LogFundingSource(
                            entity_type="FAMILY_EXPENSE_LOG",
                            entity_id=new_log.id,
                            direction=LEDGER_OUT,
                            pool_type=source.pool_type,
                            family_id=source.family_id,
                            user_id=source.user_id,
                            amount=source.amount,
                        )
                    )

            if family_amount is not None and family_amount > 0:
                family_savings_updated = family_amount

            if funding_sources:
                for source in funding_sources:
                    if source.pool_type != POOL_PERSONAL or source.user_id is None:
                        continue
                    personal_log = PersonalExpenseLog(
                        family_id=family_id,
                        user_id=source.user_id,
                        logged_by=logged_by_user_id,
                        expense_name=data.expense_name,
                        amount=source.amount,
                        expense_date=data.expense_date,
                        family_amount=family_amount,
                        family_expense_log_id=new_log.id,
                        source_type="FAMILY_EXPENSE_LOG",
                        source_id=new_log.id,
                        document_id=new_log.document_id,
                        show_doc_to_all=data.show_doc_to_all,
                        category_id=new_log.category_id,
                    )
                    self.pg_session.add(personal_log)
                if personal_amount and personal_amount > 0:
                    personal_savings_updated = personal_amount
                    personal_savings_user_id = target_user_id
                await self.pg_session.flush()
            elif personal_amount is not None and personal_amount > 0 and target_user_id:
                personal_savings_user_id = target_user_id
                personal_savings_updated = personal_amount

                personal_log = PersonalExpenseLog(
                    family_id=family_id,
                    user_id=target_user_id,
                    logged_by=logged_by_user_id,
                    expense_name=data.expense_name,
                    amount=personal_amount,
                    expense_date=data.expense_date,
                    family_amount=family_amount,
                    family_expense_log_id=new_log.id,
                    source_type="FAMILY_EXPENSE_LOG",
                    source_id=new_log.id,
                    document_id=new_log.document_id,
                    show_doc_to_all=data.show_doc_to_all,
                    category_id=new_log.category_id,
                )
                self.pg_session.add(personal_log)
                await self.pg_session.flush()

            # Sync per-user doc access (only meaningful when show_doc_to_all=False)
            if not data.show_doc_to_all and data.doc_viewer_user_ids:
                await self._sync_expense_log_doc_access(new_log.id, data.doc_viewer_user_ids)

            if funding_sources:
                await create_linked_expense_logs(
                    self.pg_session,
                    ledger,
                    primary_log_id=new_log.id,
                    primary_family_id=family_id,
                    logged_by_user_id=logged_by_user_id,
                    expense_name=data.expense_name,
                    expense_date=data.expense_date,
                    document_id=new_log.document_id,
                    show_doc_to_all=data.show_doc_to_all,
                    funding_sources=funding_sources,
                )

            await sync_log_funding_breakdown(
                self.pg_session,
                entity_type=ENTITY_FAMILY_EXPENSE_LOG,
                entity_id=new_log.id,
                host_family_id=family_id,
                show_to_family=data.show_funding_to_family,
                direction=LEDGER_OUT,
                logged_by_user_id=logged_by_user_id,
                funding_sources=funding_sources,
            )

            await self.pg_session.commit()
            await self.pg_session.refresh(new_log)
        except Exception as exc:
            await self.pg_session.rollback()
            if stored_document is not None and stored_document.file_path:
                try:
                    from app.config import db_settings
                    await self.garage_client.delete_object(
                        Bucket=db_settings.GARAGE_BUCKET_NAME,
                        Key=stored_document.file_path,
                    )
                except Exception as e:
                    logger.error("Failed to delete rolled-back document from Garage: %s", e)
            raise exc

        return new_log, family_savings_updated, personal_savings_updated, personal_savings_user_id

    async def update_family_expense_log(
        self,
        log_id: UUID,
        family_id: UUID,
        logged_by_user_id: UUID,
        data: FamilyExpenseLogUpdateRequest,
        document: UploadFile | None = None,
    ) -> tuple[FamilyExpenseLog, Decimal, Decimal | None, UUID | None]:
        """Partially update a family expense log with savings adjustments.

        Only the user who originally added the log (added_by_user_id) may edit it.
        family_amount / personal_savings_amount are optional; if sent they must sum to total_amount.

        Returns:
            Tuple of (expense_log, family_savings_delta, personal_savings_delta, personal_savings_user_id)
        """
        # Fetch the log
        log = await self.get_family_expense_log_detail(log_id, family_id)
        if log is None:
            raise ValueError("Expense log not found")

        # Ownership check
        if log.added_by_user_id != logged_by_user_id and not log.let_everyone_edit:
            raise PermissionError("Only the user who added this log can edit it")

        new_doc_path = None
        try:
            # Handle document upload / replacement
            if document is not None and document.filename:
                old_document_id = log.document_id
                if old_document_id is not None:
                    log.document_id = None
                    await self.pg_session.flush()

                stored_document = await self._document_service.replace_family_document(
                    family_id=family_id,
                    file=document,
                    old_document_id=old_document_id,
                )
                log.document_id = stored_document.id

            # Snapshot original amounts for savings adjustment
            original_family_amount: Decimal = log.family_amount or Decimal("0")
            original_personal_savings_amount: Decimal = log.personal_savings_amount or Decimal("0")
            original_personal_savings_user_id: UUID | None = log.personal_savings_user_id

            # Apply scalar field updates (exclude doc_viewer_user_ids — not a DB column)
            update_fields = data.model_dump(exclude_none=True, exclude={"doc_viewer_user_ids", "funding_sources"})
            for field, value in update_fields.items():
                setattr(log, field, value)

            if log.total_amount is not None:
                log.amount = log.total_amount

            existing_funding = await fetch_log_funding_sources(
                self.pg_session, "FAMILY_EXPENSE_LOG", log.id
            )
            spender_user_id = log.logged_by or logged_by_user_id

            family_savings_delta = Decimal("0")
            personal_savings_delta: Decimal | None = None
            personal_savings_user_id: UUID | None = None

            if data.funding_sources is not None:
                if log.total_amount is None:
                    raise ValueError("total_amount is required when updating funding_sources")
                new_funding = list(data.funding_sources)
                normalized = []
                for source in new_funding:
                    if source.pool_type == POOL_PERSONAL and source.user_id is None:
                        from app.api.schemas.funding import FundingSourceInput

                        normalized.append(
                            FundingSourceInput(
                                pool_type=POOL_PERSONAL,
                                user_id=log.personal_savings_user_id or spender_user_id,
                                amount=source.amount,
                            )
                        )
                    else:
                        normalized.append(source)
                new_funding = normalized
                validate_log_funding_sources(log.total_amount, new_funding, family_id)
                for source in new_funding:
                    await assert_user_can_fund_from(
                        self.pg_session,
                        logged_by_user_id,
                        source,
                        primary_family_id=family_id,
                    )

                new_family_amount = sum(
                    (
                        s.amount
                        for s in new_funding
                        if s.pool_type == POOL_FAMILY and s.family_id == family_id
                    ),
                    Decimal("0"),
                )
                new_personal_savings_amount, new_personal_savings_user_id = summarize_personal_funding(
                    new_funding, actor_user_id=spender_user_id
                )
                log.family_amount = new_family_amount if new_family_amount > 0 else None
                log.personal_savings_amount = (
                    new_personal_savings_amount
                    if new_personal_savings_amount and new_personal_savings_amount > 0
                    else None
                )
                log.personal_savings_user_id = new_personal_savings_user_id

                ledger = SavingsLedgerService(self.pg_session)
                old_sources = existing_funding
                if not old_sources and (
                    original_family_amount > 0 or original_personal_savings_amount > 0
                ):
                    old_sources = []
                    if original_family_amount > 0:
                        old_sources.append(
                            FundingSourceInput(
                                pool_type=POOL_FAMILY,
                                family_id=family_id,
                                amount=original_family_amount,
                            )
                        )
                    if (
                        original_personal_savings_amount > 0
                        and original_personal_savings_user_id
                    ):
                        old_sources.append(
                            FundingSourceInput(
                                pool_type=POOL_PERSONAL,
                                user_id=original_personal_savings_user_id,
                                amount=original_personal_savings_amount,
                            )
                        )
                await replace_primary_log_funding(
                    self.pg_session,
                    ledger,
                    entity_type="FAMILY_EXPENSE_LOG",
                    entity_id=log.id,
                    primary_family_id=family_id,
                    actor_user_id=spender_user_id,
                    old_sources=old_sources,
                    new_sources=new_funding,
                    apply_direction=LEDGER_OUT,
                    ledger_source_type=LEDGER_SOURCE_EXPENSE_LOG,
                )
                await remove_linked_expense_logs(
                    self.pg_session, ledger, primary_log_id=log.id
                )
                await create_linked_expense_logs(
                    self.pg_session,
                    ledger,
                    primary_log_id=log.id,
                    primary_family_id=family_id,
                    logged_by_user_id=logged_by_user_id,
                    expense_name=log.expense_name,
                    expense_date=log.expense_date,
                    document_id=log.document_id,
                    show_doc_to_all=log.show_doc_to_all,
                    funding_sources=new_funding,
                )

                await self.pg_session.execute(
                    delete(PersonalExpenseLog).where(
                        PersonalExpenseLog.family_expense_log_id == log.id
                    )
                )
                await self.pg_session.flush()
                for source in new_funding:
                    if source.pool_type != POOL_PERSONAL or source.user_id is None:
                        continue
                    self.pg_session.add(
                        PersonalExpenseLog(
                            family_id=family_id,
                            user_id=source.user_id,
                            logged_by=logged_by_user_id,
                            expense_name=log.expense_name,
                            amount=source.amount,
                            expense_date=log.expense_date,
                            family_amount=log.family_amount,
                            family_expense_log_id=log.id,
                            source_type="FAMILY_EXPENSE_LOG",
                            source_id=log.id,
                            document_id=log.document_id,
                            show_doc_to_all=log.show_doc_to_all,
                            category_id=log.category_id,
                        )
                    )
                await self.pg_session.flush()

                family_savings_delta = new_family_amount - original_family_amount
                if new_personal_savings_amount and new_personal_savings_amount > 0:
                    personal_savings_delta = new_personal_savings_amount
                    personal_savings_user_id = new_personal_savings_user_id
            else:
                if log.personal_savings_amount and log.personal_savings_amount > 0 and not log.personal_savings_user_id:
                    log.personal_savings_user_id = logged_by_user_id

                new_family_amount = log.family_amount or Decimal("0")
                new_personal_savings_amount = log.personal_savings_amount or Decimal("0")
                new_personal_savings_user_id = log.personal_savings_user_id
                new_funding = existing_funding

                errors = []
                if log.family_amount is not None or log.personal_savings_amount is not None:
                    if new_personal_savings_amount > 0 and not new_personal_savings_user_id:
                        errors.append(
                            "personal_savings_user_id is required when personal_savings_amount is set"
                        )
                    effective_total = new_family_amount + new_personal_savings_amount
                    if effective_total != log.total_amount:
                        errors.append(
                            f"family_amount ({new_family_amount}) + personal_savings_amount ({new_personal_savings_amount}) "
                            f"must equal total_amount ({log.total_amount})"
                        )
                if errors:
                    raise ValueError("; ".join(errors))

                if new_family_amount != original_family_amount:
                    family_delta = new_family_amount - original_family_amount
                    if family_delta != 0:
                        ledger = SavingsLedgerService(self.pg_session)
                        direction = LEDGER_OUT if family_delta > 0 else LEDGER_IN
                        await ledger.apply_movement(
                            SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_id),
                            abs(family_delta),
                            direction,
                            LEDGER_SOURCE_EXPENSE_LOG,
                            source_id=log.id,
                        )
                    family_savings_delta = family_delta

                personal_changed = (
                    original_personal_savings_amount != new_personal_savings_amount
                    or original_personal_savings_user_id != new_personal_savings_user_id
                )
                if personal_changed or original_personal_savings_amount > 0 or new_personal_savings_amount > 0:
                    ledger = SavingsLedgerService(self.pg_session)
                    if original_personal_savings_amount > 0 and original_personal_savings_user_id:
                        await ledger.apply_movement(
                            SavingsPoolRef(
                                pool_type=POOL_PERSONAL,
                                user_id=original_personal_savings_user_id,
                            ),
                            original_personal_savings_amount,
                            LEDGER_IN,
                            LEDGER_SOURCE_EXPENSE_LOG,
                            source_id=log.id,
                        )
                    if new_personal_savings_amount > 0 and new_personal_savings_user_id:
                        await ledger.apply_movement(
                            SavingsPoolRef(
                                pool_type=POOL_PERSONAL,
                                user_id=new_personal_savings_user_id,
                            ),
                            new_personal_savings_amount,
                            LEDGER_OUT,
                            LEDGER_SOURCE_EXPENSE_LOG,
                            source_id=log.id,
                        )
                        personal_savings_delta = new_personal_savings_amount
                        personal_savings_user_id = new_personal_savings_user_id

                stmt = select(PersonalExpenseLog).where(
                    PersonalExpenseLog.family_expense_log_id == log.id,
                    PersonalExpenseLog.family_id == family_id,
                )
                res = await self.pg_session.execute(stmt)
                personal_log = res.scalar_one_or_none()

                if new_personal_savings_amount > 0 and new_personal_savings_user_id:
                    if personal_log is not None:
                        personal_log.user_id = new_personal_savings_user_id
                        personal_log.amount = new_personal_savings_amount
                        personal_log.family_amount = log.family_amount
                        personal_log.expense_name = log.expense_name
                        personal_log.expense_date = log.expense_date
                        personal_log.document_id = log.document_id
                        personal_log.show_doc_to_all = log.show_doc_to_all
                        personal_log.category_id = log.category_id
                        self.pg_session.add(personal_log)
                        await self.pg_session.flush()
                    else:
                        personal_log = PersonalExpenseLog(
                            family_id=family_id,
                            user_id=new_personal_savings_user_id,
                            logged_by=logged_by_user_id,
                            expense_name=log.expense_name,
                            amount=new_personal_savings_amount,
                            expense_date=log.expense_date,
                            family_amount=log.family_amount,
                            family_expense_log_id=log.id,
                            source_type="FAMILY_EXPENSE_LOG",
                            source_id=log.id,
                            document_id=log.document_id,
                            show_doc_to_all=log.show_doc_to_all,
                            category_id=log.category_id,
                        )
                        self.pg_session.add(personal_log)
                        await self.pg_session.flush()
                else:
                    if personal_log is not None:
                        await self.pg_session.delete(personal_log)
                        await self.pg_session.flush()

            if data.doc_viewer_user_ids is not None:
                await self._sync_expense_log_doc_access(log.id, data.doc_viewer_user_ids)

            show_breakdown = (
                data.show_funding_to_family
                if data.show_funding_to_family is not None
                else log.show_funding_to_family
            )
            await sync_log_funding_breakdown(
                self.pg_session,
                entity_type=ENTITY_FAMILY_EXPENSE_LOG,
                entity_id=log.id,
                host_family_id=family_id,
                show_to_family=show_breakdown,
                direction=LEDGER_OUT,
                logged_by_user_id=logged_by_user_id,
                funding_sources=new_funding if new_funding else None,
            )

            await self.pg_session.commit()
            await self.pg_session.refresh(log)
        except Exception as exc:
            await self.pg_session.rollback()
            if new_doc_path is not None:
                try:
                    from app.config import db_settings
                    await self.garage_client.delete_object(
                        Bucket=db_settings.GARAGE_BUCKET_NAME,
                        Key=new_doc_path,
                    )
                except Exception as e:
                    logger.error("Failed to delete rolled-back document from Garage: %s", e)
            raise exc

        return log, family_savings_delta, personal_savings_delta, personal_savings_user_id

    # ------------------------------------------------------------------
    # Doc access helpers — recurring expense
    # ------------------------------------------------------------------

    async def _get_recurring_expense_doc_viewers(self, expense_id: UUID) -> list[UUID]:
        """Return list of user_ids who have explicit doc view access for a recurring expense."""
        stmt = select(RecurringExpenseDocAccess.user_id).where(
            RecurringExpenseDocAccess.expense_id == expense_id
        )
        result = await self.pg_session.execute(stmt)
        return list(result.scalars().all())

    async def _sync_recurring_expense_doc_access(
        self,
        expense_id: UUID,
        viewer_user_ids: list[UUID],
    ) -> None:
        """Replace the doc access rows for a recurring expense with the given user list.

        Deletes all existing rows and inserts fresh ones in a single flush.
        """
        # Delete existing access rows
        await self.pg_session.execute(
            delete(RecurringExpenseDocAccess).where(
                RecurringExpenseDocAccess.expense_id == expense_id
            )
        )
        await self.pg_session.flush()

        # Insert new access rows (deduplicated)
        seen: set[UUID] = set()
        for user_id in viewer_user_ids:
            if user_id in seen:
                continue
            seen.add(user_id)
            self.pg_session.add(RecurringExpenseDocAccess(expense_id=expense_id, user_id=user_id))

        await self.pg_session.flush()

    # ------------------------------------------------------------------
    # Doc access helpers — expense log
    # ------------------------------------------------------------------

    async def _get_expense_log_doc_viewers(self, log_id: UUID) -> list[UUID]:
        """Return list of user_ids who have explicit doc view access for an expense log."""
        stmt = select(FamilyExpenseLogDocAccess.user_id).where(
            FamilyExpenseLogDocAccess.log_id == log_id
        )
        result = await self.pg_session.execute(stmt)
        return list(result.scalars().all())

    async def _sync_expense_log_doc_access(
        self,
        log_id: UUID,
        viewer_user_ids: list[UUID],
    ) -> None:
        """Replace the doc access rows for an expense log with the given user list."""
        await self.pg_session.execute(
            delete(FamilyExpenseLogDocAccess).where(
                FamilyExpenseLogDocAccess.log_id == log_id
            )
        )
        await self.pg_session.flush()

        seen: set[UUID] = set()
        for user_id in viewer_user_ids:
            if user_id in seen:
                continue
            seen.add(user_id)
            self.pg_session.add(FamilyExpenseLogDocAccess(log_id=log_id, user_id=user_id))

        await self.pg_session.flush()

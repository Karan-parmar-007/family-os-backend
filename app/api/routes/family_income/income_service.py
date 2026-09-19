import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.document.document_service import DocumentService
from app.api.routes.family_income.income_schemas import (
    FamilyIncomeLogCreateRequest,
    FamilyIncomeLogUpdateRequest,
    FamilyIncomeLogListItem,
    PersonalIncomeLogCreateRequest,
    PersonalIncomeLogListItem,
    PersonalIncomeLogUpdateRequest,
    RecurringIncomeCreateRequest,
    RecurringIncomeQuickAddRequest,
    RecurringIncomeUpdateRequest,
    RecurringIncomeDetail,
    RecurringIncomeFamilySplitDetail,
    RecurringIncomePersonalSplitDetail,
    FamilyRecurringIncomeSummary,
    FamilySplitInput,
    PersonalSplitInput,
    _validate_income_splits,
    _validate_recurrence,
    IncomeCategoryCreateRequest,
)
from app.api.routes.family_income.model import (
    RecurringIncome,
    RecurringIncomeFamilySplit,
    RecurringIncomeDocAccess,
    FamilyIncomeLog,
    FamilyIncomeLogDocAccess,
    PersonalIncomeLog,
    FamilyIncomeCategory,
)
from app.api.routes.family.model import Family, LogFundingSource
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.funding import FundingSourceInput
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_INCOME_LOG,
    POOL_FAMILY,
    POOL_PERSONAL,
)
from app.core.funding_sources import (
    assert_user_can_fund_from,
    pool_ref_from_funding_source,
    summarize_personal_funding,
    validate_family_personal_log_split,
    validate_log_funding_sources,
)
from app.core.split_log_helpers import (
    create_linked_income_logs,
    fetch_log_funding_sources,
    is_other_family_source,
    remove_linked_income_logs,
    replace_primary_log_funding,
    resolve_let_everyone_edit,
)
from app.core.log_breakdown_helpers import (
    ENTITY_FAMILY_INCOME_LOG,
    log_ids_with_breakdown,
    sync_log_funding_breakdown,
)
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.scope import ScopeContext, can_view_income_log, can_view_scoped_entity
from app.api.routes.user.model import UserBase
from app.api.schemas.pagination import PaginationParams

logger = logging.getLogger(__name__)


class IncomeService:
    def __init__(self, pg_session: AsyncSession, garage_client: Any):
        self.pg_session = pg_session
        self.garage_client = garage_client
        self._document_service = DocumentService(pg_session, garage_client)

    async def get_default_category_id(self, family_id: UUID) -> UUID:
        stmt = select(FamilyIncomeCategory).where(
            FamilyIncomeCategory.family_id == family_id,
            FamilyIncomeCategory.category_name == "Other"
        )
        cat = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if cat is not None:
            return cat.id
        import uuid6
        cat = FamilyIncomeCategory(
            id=uuid6.uuid7(),
            family_id=family_id,
            category_name="Other"
        )
        self.pg_session.add(cat)
        await self.pg_session.flush()
        return cat.id

    async def list_categories(self, family_id: UUID) -> list[FamilyIncomeCategory]:
        stmt = (
            select(FamilyIncomeCategory)
            .where(FamilyIncomeCategory.family_id == family_id)
            .order_by(FamilyIncomeCategory.category_name.asc())
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def create_category(
        self, family_id: UUID, request: IncomeCategoryCreateRequest
    ) -> FamilyIncomeCategory:
        stmt = select(FamilyIncomeCategory).where(
            FamilyIncomeCategory.family_id == family_id,
            FamilyIncomeCategory.category_name == request.category_name
        )
        existing = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing
        import uuid6
        cat = FamilyIncomeCategory(
            id=uuid6.uuid7(),
            family_id=family_id,
            category_name=request.category_name
        )
        self.pg_session.add(cat)
        await self.pg_session.commit()
        await self.pg_session.refresh(cat)
        return cat

    # ------------------------------------------------------------------
    # Recurring income queries
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

    async def _get_splits_for_income(
        self, income_id: UUID
    ) -> list[RecurringIncomeFamilySplit]:
        stmt = select(RecurringIncomeFamilySplit).where(
            RecurringIncomeFamilySplit.income_id == income_id
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def _build_recurring_detail(
        self,
        income: RecurringIncome,
        *,
        viewer_user_id: UUID | None = None,
        family_id: UUID | None = None,
    ) -> RecurringIncomeDetail:
        splits = await self._get_splits_for_income(income.id)
        family_names: dict[UUID, str] = {}
        if splits:
            fam_stmt = select(Family).where(
                Family.id.in_([s.family_id for s in splits])
            )
            for fam in (await self.pg_session.execute(fam_stmt)).scalars().all():
                family_names[fam.id] = fam.name

        viewer_ids = await self._get_recurring_income_doc_viewers(income.id)
        detail = RecurringIncomeDetail.model_validate(income)
        detail.doc_viewer_user_ids = viewer_ids
        detail.family_splits = [
            RecurringIncomeFamilySplitDetail(
                family_id=s.family_id,
                family_name=family_names.get(s.family_id),
                split_name=s.split_name,
                amount=s.amount,
            )
            for s in splits
        ]
        from app.api.routes.family_income.model import RecurringIncomePersonalSplit

        personal_rows = list(
            (
                await self.pg_session.execute(
                    select(RecurringIncomePersonalSplit).where(
                        RecurringIncomePersonalSplit.income_id == income.id
                    )
                )
            ).scalars().all()
        )
        detail.personal_splits = [
            RecurringIncomePersonalSplitDetail(user_id=r.user_id, amount=r.amount)
            for r in personal_rows
        ]
        if viewer_user_id is not None:
            detail.can_edit = await self.can_edit_recurring_income(
                viewer_user_id, income, family_id=family_id
            )
        return detail

    async def can_edit_recurring_income(
        self,
        user_id: UUID,
        income: RecurringIncome,
        *,
        family_id: UUID | None = None,
    ) -> bool:
        if income.user_id == user_id:
            return True
        if not income.is_family_managed or not income.let_everyone_edit:
            return False
        if family_id is None:
            return False
        splits = await self._get_splits_for_income(income.id)
        if not any(s.family_id == family_id for s in splits):
            return False
        try:
            await self._assert_user_in_families(user_id, [family_id])
        except ValueError:
            return False
        return True

    async def list_user_recurring_incomes(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        personal_only: bool = False,
    ) -> tuple[list[RecurringIncomeDetail], int]:
        filters: list[Any] = [RecurringIncome.user_id == user_id]
        if personal_only:
            filters.append(RecurringIncome.is_family_managed.is_(False))
        count_stmt = (
            select(func.count()).select_from(RecurringIncome).where(*filters)
        )
        total_count = (await self.pg_session.execute(count_stmt)).scalar_one()

        stmt = (
            select(RecurringIncome)
            .where(*filters)
            .order_by(RecurringIncome.created_at.desc())  # type: ignore[attr-defined]
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        incomes = list((await self.pg_session.execute(stmt)).scalars().all())
        items = [
            await self._build_recurring_detail(inc, viewer_user_id=user_id)
            for inc in incomes
        ]
        return items, total_count

    async def list_my_family_managed_recurring_incomes(
        self,
        user_id: UUID,
        family_id: UUID,
        pagination: PaginationParams,
    ) -> tuple[list[RecurringIncomeDetail], int]:
        """Current user's family-managed recurring incomes with a split in this family."""
        stmt = (
            select(RecurringIncome)
            .join(
                RecurringIncomeFamilySplit,
                RecurringIncomeFamilySplit.income_id == RecurringIncome.id,
            )
            .where(
                RecurringIncomeFamilySplit.family_id == family_id,
                RecurringIncome.is_family_managed.is_(True),
                RecurringIncome.user_id == user_id,
            )
            .order_by(RecurringIncome.created_at.desc())  # type: ignore[attr-defined]
        )
        rows = list((await self.pg_session.execute(stmt)).scalars().all())
        seen: set[UUID] = set()
        incomes: list[RecurringIncome] = []
        for inc in rows:
            if inc.id in seen:
                continue
            seen.add(inc.id)
            incomes.append(inc)

        total_count = len(incomes)
        page = incomes[pagination.offset : pagination.offset + pagination.page_size]
        items = [
            await self._build_recurring_detail(
                inc, viewer_user_id=user_id, family_id=family_id
            )
            for inc in page
        ]
        return items, total_count

    async def list_family_recurring_income_splits(
        self,
        family_id: UUID,
        pagination: PaginationParams,
    ) -> tuple[list[FamilyRecurringIncomeSummary], int]:
        stmt = (
            select(RecurringIncomeFamilySplit, RecurringIncome)
            .join(RecurringIncome, RecurringIncome.id == RecurringIncomeFamilySplit.income_id)
            .where(RecurringIncomeFamilySplit.family_id == family_id)
            .order_by(RecurringIncome.created_at.desc())  # type: ignore[attr-defined]
        )
        rows = list((await self.pg_session.execute(stmt)).all())
        items = [
            FamilyRecurringIncomeSummary(
                id=split.id,
                recurring_income_id=income.id,
                split_name=split.split_name,
                amount=split.amount,
                received_every=income.received_every,
                repeat_interval_days=income.repeat_interval_days,
                repeat_interval_months=income.repeat_interval_months,
                repeat_interval_years=income.repeat_interval_years,
                next_receiving_date=income.next_receiving_date,
                earned_by_user_id=income.user_id,
            )
            for split, income in rows
        ]
        total_count = len(items)
        page = items[pagination.offset : pagination.offset + pagination.page_size]
        return page, total_count

    # ------------------------------------------------------------------
    # Recurring income mutations
    # ------------------------------------------------------------------

    async def _sync_family_splits(
        self,
        income_id: UUID,
        splits: list[FamilySplitInput],
    ) -> None:
        await self.pg_session.execute(
            delete(RecurringIncomeFamilySplit).where(
                RecurringIncomeFamilySplit.income_id == income_id
            )
        )
        await self.pg_session.flush()
        for split in splits:
            self.pg_session.add(
                RecurringIncomeFamilySplit(
                    income_id=income_id,
                    family_id=split.family_id,
                    split_name=split.split_name,
                    amount=split.amount,
                )
            )
        await self.pg_session.flush()

    async def _sync_personal_splits(
        self,
        income_id: UUID,
        splits: list,
        *,
        owner_user_id: UUID,
        personal_amount: Decimal | None,
    ) -> None:
        from app.api.routes.family_income.model import RecurringIncomePersonalSplit
        from app.api.routes.family_income.income_schemas import PersonalSplitInput
        from app.api.routes.friend.friend_service import FriendService

        await self.pg_session.execute(
            delete(RecurringIncomePersonalSplit).where(
                RecurringIncomePersonalSplit.income_id == income_id
            )
        )
        await self.pg_session.flush()

        resolved: list[PersonalSplitInput] = list(splits or [])
        if not resolved and personal_amount and personal_amount > 0:
            resolved = [PersonalSplitInput(user_id=owner_user_id, amount=personal_amount)]

        friend_service = FriendService(self.pg_session)
        for split in resolved:
            await friend_service.assert_can_allocate_to_personal(owner_user_id, split.user_id)
            self.pg_session.add(
                RecurringIncomePersonalSplit(
                    income_id=income_id,
                    user_id=split.user_id,
                    amount=split.amount,
                )
            )
        await self.pg_session.flush()

    async def create_recurring_income(
        self,
        user_id: UUID,
        data: RecurringIncomeCreateRequest,
        document: UploadFile | None = None,
        *,
        document_family_id: UUID | None = None,
        is_family_managed: bool = False,
        let_everyone_edit: bool = False,
    ) -> RecurringIncome:
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

        # Resolve category_id
        category_id = data.category_id
        if not category_id:
            family_id = None
            if data.family_splits:
                family_id = data.family_splits[0].family_id
            else:
                stmt_fam = select(UserFamilyLink.family_id).where(UserFamilyLink.user_id == user_id)
                family_id = (await self.pg_session.execute(stmt_fam)).scalars().first()
            if family_id:
                category_id = await self.get_default_category_id(family_id)

        target_user_id = data.earned_by_user_id or user_id
        if data.personal_splits:
            personal = sum((s.amount for s in data.personal_splits), Decimal("0"))
        else:
            personal = data.personal_savings_amount if data.personal_savings_amount else None
        income = RecurringIncome(
            user_id=target_user_id,
            added_by_user_id=user_id,
            income_name=data.income_name,
            total_amount=data.total_amount,
            personal_savings_amount=personal if personal else None,
            received_every=data.received_every,
            repeat_interval_days=data.repeat_interval_days,
            repeat_interval_months=data.repeat_interval_months,
            repeat_interval_years=data.repeat_interval_years,
            next_receiving_date=data.next_receiving_date,
            document_id=document_id,
            show_docs_to_all=data.show_docs_to_all,
            repeat_doc_with_logs=data.repeat_doc_with_logs,
            is_family_managed=is_family_managed,
            let_everyone_edit=let_everyone_edit if is_family_managed else False,
            category_id=category_id,
        )
        self.pg_session.add(income)
        await self.pg_session.flush()

        if data.family_splits:
            await self._sync_family_splits(income.id, data.family_splits)

        await self._sync_personal_splits(
            income.id,
            getattr(data, "personal_splits", None) or [],
            owner_user_id=target_user_id,
            personal_amount=personal,
        )

        if not data.show_docs_to_all and data.doc_viewer_user_ids:
            await self._sync_recurring_income_doc_access(income.id, data.doc_viewer_user_ids)

        from app.scheduler.income_cron import create_or_replace_next_job

        await create_or_replace_next_job(self.pg_session, income)
        await self.pg_session.commit()
        await self.pg_session.refresh(income)
        return income

    async def quick_add_recurring_income(
        self,
        user_id: UUID,
        family_id: UUID,
        data: RecurringIncomeQuickAddRequest,
        document: UploadFile | None = None,
    ) -> RecurringIncome:
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
                    split_name=data.split_name or data.income_name,
                    amount=family_amount,
                )
            )
        create_data = RecurringIncomeCreateRequest(
            income_name=data.income_name,
            total_amount=data.total_amount,
            personal_savings_amount=personal if personal > 0 else None,
            personal_splits=personal_splits,
            family_splits=splits,
            received_every=data.received_every,
            repeat_interval_days=data.repeat_interval_days,
            repeat_interval_months=data.repeat_interval_months,
            repeat_interval_years=data.repeat_interval_years,
            next_receiving_date=data.next_receiving_date,
            show_docs_to_all=data.show_docs_to_all,
            repeat_doc_with_logs=data.repeat_doc_with_logs,
            doc_viewer_user_ids=data.doc_viewer_user_ids,
            category_id=data.category_id,
            earned_by_user_id=data.earned_by_user_id,
        )
        return await self.create_recurring_income(
            user_id,
            create_data,
            document,
            document_family_id=family_id,
            is_family_managed=True,
            let_everyone_edit=data.let_everyone_edit,
        )

    async def update_recurring_income(
        self,
        income: RecurringIncome,
        data: RecurringIncomeUpdateRequest,
        document: UploadFile | None = None,
        *,
        document_family_id: UUID | None = None,
    ) -> RecurringIncome:
        if document is not None and document.filename:
            store_family = document_family_id
            if store_family is None:
                splits = await self._get_splits_for_income(income.id)
                store_family = splits[0].family_id if splits else None
            if store_family is None:
                raise ValueError("Cannot replace document without a family context")
            old_document_id = income.document_id
            if old_document_id is not None:
                income.document_id = None
                await self.pg_session.flush()
            stored_document = await self._document_service.replace_family_document(
                family_id=store_family,
                file=document,
                old_document_id=old_document_id,
            )
            income.document_id = stored_document.id

        recurrence_fields = {
            "received_every",
            "repeat_interval_days",
            "repeat_interval_months",
            "repeat_interval_years",
            "next_receiving_date",
        }
        update_data = data.model_dump(exclude={"doc_viewer_user_ids", "family_splits", "earned_by_user_id", "personal_splits"})
        for field, value in update_data.items():
            if field in recurrence_fields:
                continue
            if value is not None:
                setattr(income, field, value)

        if data.earned_by_user_id is not None:
            income.user_id = data.earned_by_user_id

        if data.next_receiving_date is not None:
            income.received_every = data.received_every
            income.repeat_interval_days = data.repeat_interval_days
            income.repeat_interval_months = data.repeat_interval_months
            income.repeat_interval_years = data.repeat_interval_years
            income.next_receiving_date = data.next_receiving_date

        if data.family_splits is not None:
            await self._assert_user_in_families(
                income.user_id, [s.family_id for s in data.family_splits]
            )
            await self._sync_family_splits(income.id, data.family_splits)

        if data.personal_splits is not None:
            personal_sum = sum((s.amount for s in data.personal_splits), Decimal("0"))
            income.personal_savings_amount = personal_sum if personal_sum > 0 else None
            await self._sync_personal_splits(
                income.id,
                data.personal_splits,
                owner_user_id=income.user_id,
                personal_amount=income.personal_savings_amount,
            )
        elif data.personal_savings_amount is not None:
            await self._sync_personal_splits(
                income.id,
                [],
                owner_user_id=income.user_id,
                personal_amount=data.personal_savings_amount,
            )

        splits = await self._get_splits_for_income(income.id)
        from app.api.routes.family_income.model import RecurringIncomePersonalSplit

        personal_rows = list(
            (
                await self.pg_session.execute(
                    select(RecurringIncomePersonalSplit).where(
                        RecurringIncomePersonalSplit.income_id == income.id
                    )
                )
            ).scalars().all()
        )
        personal_split_inputs = [
            PersonalSplitInput(user_id=r.user_id, amount=r.amount) for r in personal_rows
        ]
        _validate_income_splits(
            income.total_amount,
            income.personal_savings_amount,
            [
                FamilySplitInput(
                    family_id=s.family_id, split_name=s.split_name, amount=s.amount
                )
                for s in splits
            ],
            personal_split_inputs or None,
        )
        _validate_recurrence(
            income.received_every,
            income.repeat_interval_days,
            income.repeat_interval_months,
            income.repeat_interval_years,
        )
        if income.next_receiving_date is None:
            raise ValueError("next_receiving_date is required")

        if data.doc_viewer_user_ids is not None:
            await self._sync_recurring_income_doc_access(income.id, data.doc_viewer_user_ids)

        if data.let_everyone_edit is not None:
            if not income.is_family_managed:
                raise ValueError("let_everyone_edit applies only to family recurring income")
            income.let_everyone_edit = data.let_everyone_edit

        from app.scheduler.income_cron import create_or_replace_next_job

        await create_or_replace_next_job(self.pg_session, income)
        await self.pg_session.commit()
        await self.pg_session.refresh(income)
        return income

    async def cancel_recurring_income(self, income: RecurringIncome) -> RecurringIncome:
        income.next_receiving_date = None
        from app.scheduler.income_cron import cancel_pending_income_jobs

        await cancel_pending_income_jobs(self.pg_session, income.id)
        await self.pg_session.commit()
        await self.pg_session.refresh(income)
        return income

    # Legacy aliases
    async def list_family_recurring_incomes_added_by_user(self, *args, **kwargs):
        return await self.list_user_recurring_incomes(*args, **kwargs)

    async def list_family_recurring_incomes(self, family_id, pagination, **kwargs):
        return await self.list_family_recurring_income_splits(family_id, pagination)

    async def create_family_recurring_income(self, family_id, added_by_user_id, data, document=None):
        raise NotImplementedError("Use quick_add_recurring_income or create_recurring_income")

    async def update_family_recurring_income(self, *args, **kwargs):
        raise NotImplementedError("Use update_recurring_income from personal routes")

    async def cancel_family_recurring_income(self, income):
        return await self.cancel_recurring_income(income)

    # ------------------------------------------------------------------
    # Income log queries
    # ------------------------------------------------------------------

    async def list_family_income_logs(
        self,
        family_id: UUID,
        current_user_id: UUID,
        pagination: PaginationParams,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        earned_by_user_id: UUID | None = None,
        category_id: UUID | None = None,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[FamilyIncomeLogListItem], int]:
        """Fetch a paginated list of family income logs with optional filters.

        Joins the users table to resolve earned_by_user_id → name.
        Returns limited fields suitable for the list view.
        """
        filters = [FamilyIncomeLog.family_id == family_id]
        if start_date is not None:
            filters.append(FamilyIncomeLog.income_date >= start_date)
        if end_date is not None:
            filters.append(FamilyIncomeLog.income_date <= end_date)
        if earned_by_user_id is not None:
            filters.append(FamilyIncomeLog.earned_by_user_id == earned_by_user_id)
        if category_id is not None:
            filters.append(FamilyIncomeLog.category_id == category_id)

        stmt = (
            select(FamilyIncomeLog, UserBase.name, FamilyIncomeCategory.category_name)
            .outerjoin(
                UserBase,
                FamilyIncomeLog.earned_by_user_id == UserBase.id,
            )
            .outerjoin(
                FamilyIncomeCategory,
                FamilyIncomeLog.category_id == FamilyIncomeCategory.id,
            )
            .where(*filters)
            .order_by(FamilyIncomeLog.income_date.desc())  # type: ignore[attr-defined]
        )
        result = await self.pg_session.execute(stmt)
        rows = result.all()

        if scope_ctx is not None:
            rows = [(log, name, cat_name) for log, name, cat_name in rows if can_view_income_log(scope_ctx, log)]

        total_count = len(rows)
        rows = rows[pagination.offset : pagination.offset + pagination.page_size]

        breakdown_ids = await log_ids_with_breakdown(
            self.pg_session,
            ENTITY_FAMILY_INCOME_LOG,
            [log.id for log, _, _ in rows],
        )

        items: list[FamilyIncomeLogListItem] = []
        for log, earned_name, category_name in rows:
            viewer_ids = await self._get_income_log_doc_viewers(log.id)
            items.append(
                FamilyIncomeLogListItem(
                    id=log.id,
                    income_name=log.income_name,
                    source_type=log.source_type,
                    income_date=log.income_date,
                    added_by_user_id=log.added_by_user_id,
                    total_amount=log.total_amount,
                    family_amount=log.family_amount,
                    personal_savings_amount=log.personal_savings_amount,
                    personal_savings_user_id=log.personal_savings_user_id,
                    earned_by_user_name=earned_name,
                    earned_by_user_id=log.earned_by_user_id,
                    document_id=log.document_id,
                    show_doc_to_all=log.show_doc_to_all,
                    doc_viewer_user_ids=viewer_ids,
                    can_edit=(
                        ((log.earned_by_user_id or log.added_by_user_id) == current_user_id)
                        or log.let_everyone_edit
                    ),
                    let_everyone_edit=log.let_everyone_edit,
                    has_breakdown=log.id in breakdown_ids,
                    category_id=log.category_id,
                    category_name=category_name,
                )
            )

        return items, total_count

    async def list_personal_income_logs(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        category_id: UUID | None = None,
    ) -> tuple[list[PersonalIncomeLogListItem], int]:
        """List personal income logs where the user received personal savings."""
        filters = [PersonalIncomeLog.user_id == user_id]
        if start_date is not None:
            filters.append(PersonalIncomeLog.income_date >= start_date)
        if end_date is not None:
            filters.append(PersonalIncomeLog.income_date <= end_date)
        if category_id is not None:
            filters.append(PersonalIncomeLog.category_id == category_id)

        stmt = (
            select(PersonalIncomeLog, Family.name, FamilyIncomeCategory.category_name)
            .outerjoin(Family, PersonalIncomeLog.family_id == Family.id)
            .outerjoin(
                FamilyIncomeCategory,
                PersonalIncomeLog.category_id == FamilyIncomeCategory.id,
            )
            .where(*filters)
            .order_by(PersonalIncomeLog.income_date.desc())  # type: ignore[attr-defined]
        )
        rows = (await self.pg_session.execute(stmt)).all()
        total_count = len(rows)
        rows = rows[pagination.offset : pagination.offset + pagination.page_size]

        items: list[PersonalIncomeLogListItem] = []
        for log, family_name, category_name in rows:
            items.append(
                PersonalIncomeLogListItem(
                    id=log.id,
                    income_name=log.income_name,
                    amount=log.amount,
                    income_date=log.income_date,
                    source_type=log.source_type,
                    family_id=log.family_id,
                    family_name=family_name,
                    family_income_log_id=log.family_income_log_id,
                    document_id=log.document_id,
                    show_doc_to_all=log.show_doc_to_all,
                    can_edit=log.source_type == "MANUAL" and log.logged_by == user_id,
                    category_id=log.category_id,
                    category_name=category_name,
                )
            )
        return items, total_count

    async def get_personal_income_log_detail(
        self,
        log_id: UUID,
        user_id: UUID,
    ) -> PersonalIncomeLog | None:
        stmt = select(PersonalIncomeLog).where(
            PersonalIncomeLog.id == log_id,
            PersonalIncomeLog.user_id == user_id,
        )
        return (await self.pg_session.execute(stmt)).scalar_one_or_none()

    async def create_personal_income_log(
        self,
        user_id: UUID,
        data: PersonalIncomeLogCreateRequest,
        document: UploadFile | None = None,
    ) -> tuple[PersonalIncomeLog, Decimal]:
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

            log = PersonalIncomeLog(
                family_id=None,
                user_id=user_id,
                logged_by=user_id,
                income_name=data.income_name,
                amount=data.amount,
                income_date=data.income_date,
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
                LEDGER_IN,
                LEDGER_SOURCE_INCOME_LOG,
                source_id=log.id,
                occurred_at=data.income_date,
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

    async def update_personal_income_log(
        self,
        log_id: UUID,
        user_id: UUID,
        data: PersonalIncomeLogUpdateRequest,
        document: UploadFile | None = None,
    ) -> tuple[PersonalIncomeLog, Decimal]:
        log = await self.get_personal_income_log_detail(log_id, user_id)
        if log is None:
            raise ValueError("Income log not found")
        if log.source_type != "MANUAL":
            raise PermissionError("Only manually added personal income logs can be edited here")
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

        if data.income_name is not None:
            log.income_name = data.income_name
        if data.income_date is not None:
            log.income_date = data.income_date
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
                        LEDGER_OUT,
                        LEDGER_SOURCE_INCOME_LOG,
                        source_id=log.id,
                    )
                if new_amount > 0:
                    await ledger.apply_movement(
                        SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user_id),
                        new_amount,
                        LEDGER_IN,
                        LEDGER_SOURCE_INCOME_LOG,
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

    async def get_family_income_log_detail(
        self,
        log_id: UUID,
        family_id: UUID,
    ) -> FamilyIncomeLog | None:
        """Fetch full detail of a family income log by ID."""
        stmt = select(FamilyIncomeLog).where(
            FamilyIncomeLog.id == log_id,
            FamilyIncomeLog.family_id == family_id,
        )
        result = await self.pg_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_family_income_log_detail_with_access(
        self,
        log_id: UUID,
        family_id: UUID,
    ) -> tuple[FamilyIncomeLog, list[UUID]] | None:
        """Fetch full detail of a family income log along with its doc viewer ids."""
        log = await self.get_family_income_log_detail(log_id, family_id)
        if log is None:
            return None
        viewer_ids = await self._get_income_log_doc_viewers(log_id)
        return log, viewer_ids

    # ------------------------------------------------------------------
    # Income log mutations
    # ------------------------------------------------------------------

    async def create_family_income_log(
        self,
        family_id: UUID,
        logged_by_user_id: UUID,
        data: FamilyIncomeLogCreateRequest,
        document: UploadFile | None = None,
    ) -> tuple[FamilyIncomeLog, Decimal, Decimal | None, UUID | None]:
        """Create a family income log and update savings totals.

        family_amount and personal_savings_amount are optional.
        If neither (and no funding_sources) is provided, the full total credits
        this family's savings. If provided, they must sum to total_amount.

        Returns:
            Tuple of (income_log, family_savings_updated, personal_savings_updated, personal_savings_user_id)
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

        # Resolve earned_by_user_id: can be someone else
        earned_by_user_id = data.earned_by_user_id or logged_by_user_id

        family_amount = data.family_amount
        personal_amount = data.personal_savings_amount
        funding_sources = data.funding_sources
        # Total only → 100% to this family's savings (same default as recurring quick-add)
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
                personal_target = data.personal_savings_user_id or earned_by_user_id
                funding_sources.append(
                    FundingSourceInput(
                        pool_type=POOL_PERSONAL,
                        user_id=personal_target,
                        amount=personal_amount,
                    )
                )
        if funding_sources:
            # Backfill missing PERSONAL user_id for legacy clients
            normalized: list[FundingSourceInput] = []
            for source in funding_sources:
                if source.pool_type == POOL_PERSONAL and source.user_id is None:
                    normalized.append(
                        FundingSourceInput(
                            pool_type=POOL_PERSONAL,
                            user_id=data.personal_savings_user_id or earned_by_user_id,
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
                    logged_by_user_id,
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
                funding_sources, actor_user_id=earned_by_user_id
            )
        else:
            target_user_id = (
                data.personal_savings_user_id or earned_by_user_id
                if personal_amount and personal_amount > 0
                else None
            )
        let_everyone = resolve_let_everyone_edit(
            data.let_everyone_edit,
            funding_sources,
            family_id,
            personal_amount,
        )

        category_id = data.category_id
        if not category_id:
            category_id = await self.get_default_category_id(family_id)

        try:
            new_log = FamilyIncomeLog(
                family_id=family_id,
                scope_type=data.scope_type,
                logged_by=logged_by_user_id,
                income_name=data.income_name,
                total_amount=data.total_amount,
                family_amount=family_amount,
                income_date=data.income_date,
                source_type="MANUAL",
                source_id=None,
                personal_savings_amount=personal_amount if personal_amount else None,
                personal_savings_user_id=target_user_id,
                earned_by_user_id=earned_by_user_id,
                document_id=document_id or data.document_id,
                added_by_user_id=logged_by_user_id,
                show_doc_to_all=data.show_doc_to_all,
                let_everyone_edit=let_everyone,
                show_funding_to_family=data.show_funding_to_family,
                category_id=category_id,
            )
            self.pg_session.add(new_log)
            await self.pg_session.flush()

            family_savings_updated = Decimal("0")
            personal_savings_updated: Decimal | None = None
            personal_savings_user_id: UUID | None = None

            ledger = SavingsLedgerService(self.pg_session)
            if funding_sources:
                for source in funding_sources:
                    if is_other_family_source(source, family_id):
                        continue
                    pool = pool_ref_from_funding_source(earned_by_user_id, source)
                    await ledger.apply_movement(
                        pool,
                        source.amount,
                        LEDGER_IN,
                        LEDGER_SOURCE_INCOME_LOG,
                        source_id=new_log.id,
                    )
                    self.pg_session.add(
                        LogFundingSource(
                            entity_type="FAMILY_INCOME_LOG",
                            entity_id=new_log.id,
                            direction=LEDGER_IN,
                            pool_type=source.pool_type,
                            family_id=source.family_id,
                            user_id=source.user_id,
                            amount=source.amount,
                        )
                    )

            if family_amount is not None and family_amount > 0:
                family_savings_updated = family_amount

            if funding_sources:
                from app.api.routes.family_income.model import PersonalIncomeLog

                for source in funding_sources:
                    if source.pool_type != POOL_PERSONAL or source.user_id is None:
                        continue
                    personal_log = PersonalIncomeLog(
                        family_id=family_id,
                        user_id=source.user_id,
                        logged_by=logged_by_user_id,
                        income_name=data.income_name,
                        amount=source.amount,
                        income_date=data.income_date,
                        family_amount=family_amount,
                        family_income_log_id=new_log.id,
                        source_type="FAMILY_INCOME_LOG",
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

                from app.api.routes.family_income.model import PersonalIncomeLog
                personal_log = PersonalIncomeLog(
                    family_id=family_id,
                    user_id=target_user_id,
                    logged_by=logged_by_user_id,
                    income_name=data.income_name,
                    amount=personal_amount,
                    income_date=data.income_date,
                    family_amount=family_amount,
                    family_income_log_id=new_log.id,
                    source_type="FAMILY_INCOME_LOG",
                    source_id=new_log.id,
                    document_id=new_log.document_id,
                    show_doc_to_all=data.show_doc_to_all,
                    category_id=new_log.category_id,
                )
                self.pg_session.add(personal_log)
                await self.pg_session.flush()

            # Sync per-user doc access (only meaningful when show_doc_to_all=False)
            if not data.show_doc_to_all and data.doc_viewer_user_ids:
                await self._sync_income_log_doc_access(new_log.id, data.doc_viewer_user_ids)

            if funding_sources:
                await create_linked_income_logs(
                    self.pg_session,
                    ledger,
                    primary_log_id=new_log.id,
                    primary_family_id=family_id,
                    logged_by_user_id=logged_by_user_id,
                    income_name=data.income_name,
                    income_date=data.income_date,
                    document_id=new_log.document_id,
                    show_doc_to_all=data.show_doc_to_all,
                    funding_sources=funding_sources,
                )

            await sync_log_funding_breakdown(
                self.pg_session,
                entity_type=ENTITY_FAMILY_INCOME_LOG,
                entity_id=new_log.id,
                host_family_id=family_id,
                show_to_family=data.show_funding_to_family,
                direction=LEDGER_IN,
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

    async def update_family_income_log(
        self,
        log_id: UUID,
        family_id: UUID,
        logged_by_user_id: UUID,
        data: FamilyIncomeLogUpdateRequest,
        document: UploadFile | None = None,
    ) -> tuple[FamilyIncomeLog, Decimal, Decimal | None, UUID | None]:
        """Partially update a family income log with savings adjustments.

        Only the user who originally added the log (added_by_user_id) may edit it.
        family_amount / personal_savings_amount are optional; if sent they must sum to total_amount.

        Returns:
            Tuple of (income_log, family_savings_delta, personal_savings_delta, personal_savings_user_id)
        """
        # Fetch the log
        log = await self.get_family_income_log_detail(log_id, family_id)
        if log is None:
            raise ValueError("Income log not found")

        # Ownership check
        earner_user_id = log.earned_by_user_id or log.added_by_user_id
        if earner_user_id != logged_by_user_id and not log.let_everyone_edit:
            raise PermissionError("Only the user who earned this income may edit it")

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

            existing_funding = await fetch_log_funding_sources(
                self.pg_session, "FAMILY_INCOME_LOG", log.id
            )
            earner_user_id = log.earned_by_user_id or logged_by_user_id

            family_savings_delta = Decimal("0")
            personal_savings_delta: Decimal | None = None
            personal_savings_user_id: UUID | None = None

            from app.api.routes.family_income.model import PersonalIncomeLog
            from app.core.constants import POOL_PERSONAL

            if data.funding_sources is not None:
                if log.total_amount is None:
                    raise ValueError("total_amount is required when updating funding_sources")
                new_funding = list(data.funding_sources)
                normalized: list = []
                for source in new_funding:
                    if source.pool_type == POOL_PERSONAL and source.user_id is None:
                        from app.api.schemas.funding import FundingSourceInput
                        normalized.append(
                            FundingSourceInput(
                                pool_type=POOL_PERSONAL,
                                user_id=log.personal_savings_user_id or earner_user_id,
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
                    new_funding, actor_user_id=earner_user_id
                )
                log.family_amount = new_family_amount if new_family_amount > 0 else None
                log.personal_savings_amount = (
                    new_personal_savings_amount if new_personal_savings_amount and new_personal_savings_amount > 0 else None
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
                    entity_type="FAMILY_INCOME_LOG",
                    entity_id=log.id,
                    primary_family_id=family_id,
                    actor_user_id=earner_user_id,
                    old_sources=old_sources,
                    new_sources=new_funding,
                    apply_direction=LEDGER_IN,
                    ledger_source_type=LEDGER_SOURCE_INCOME_LOG,
                )
                await remove_linked_income_logs(
                    self.pg_session, ledger, primary_log_id=log.id
                )
                await create_linked_income_logs(
                    self.pg_session,
                    ledger,
                    primary_log_id=log.id,
                    primary_family_id=family_id,
                    logged_by_user_id=logged_by_user_id,
                    income_name=log.income_name,
                    income_date=log.income_date,
                    document_id=log.document_id,
                    show_doc_to_all=log.show_doc_to_all,
                    funding_sources=new_funding,
                )

                await self.pg_session.execute(
                    delete(PersonalIncomeLog).where(
                        PersonalIncomeLog.family_income_log_id == log.id
                    )
                )
                await self.pg_session.flush()
                for source in new_funding:
                    if source.pool_type != POOL_PERSONAL or source.user_id is None:
                        continue
                    self.pg_session.add(
                        PersonalIncomeLog(
                            family_id=family_id,
                            user_id=source.user_id,
                            logged_by=logged_by_user_id,
                            income_name=log.income_name,
                            amount=source.amount,
                            income_date=log.income_date,
                            family_amount=log.family_amount,
                            family_income_log_id=log.id,
                            source_type="FAMILY_INCOME_LOG",
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
                new_family_amount = log.family_amount or Decimal("0")
                new_personal_savings_amount = log.personal_savings_amount or Decimal("0")
                new_personal_savings_user_id = log.personal_savings_user_id
                new_funding = existing_funding

                errors = []
                if log.family_amount is not None or log.personal_savings_amount is not None:
                    try:
                        validate_family_personal_log_split(
                            log.total_amount,
                            log.family_amount,
                            log.personal_savings_amount,
                        )
                    except ValueError as exc:
                        errors.append(str(exc))
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
                        direction = LEDGER_IN if family_delta > 0 else LEDGER_OUT
                        await ledger.apply_movement(
                            SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_id),
                            abs(family_delta),
                            direction,
                            LEDGER_SOURCE_INCOME_LOG,
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
                            LEDGER_OUT,
                            LEDGER_SOURCE_INCOME_LOG,
                            source_id=log.id,
                        )
                    if new_personal_savings_amount > 0 and new_personal_savings_user_id:
                        await ledger.apply_movement(
                            SavingsPoolRef(
                                pool_type=POOL_PERSONAL,
                                user_id=new_personal_savings_user_id,
                            ),
                            new_personal_savings_amount,
                            LEDGER_IN,
                            LEDGER_SOURCE_INCOME_LOG,
                            source_id=log.id,
                        )
                        personal_savings_delta = new_personal_savings_amount
                        personal_savings_user_id = new_personal_savings_user_id

                stmt = select(PersonalIncomeLog).where(
                    PersonalIncomeLog.family_income_log_id == log.id,
                    PersonalIncomeLog.family_id == family_id,
                )
                res = await self.pg_session.execute(stmt)
                personal_log = res.scalar_one_or_none()

                if new_personal_savings_amount > 0 and new_personal_savings_user_id:
                    if personal_log is not None:
                        personal_log.user_id = new_personal_savings_user_id
                        personal_log.amount = new_personal_savings_amount
                        personal_log.family_amount = log.family_amount
                        personal_log.income_name = log.income_name
                        personal_log.income_date = log.income_date
                        personal_log.document_id = log.document_id
                        personal_log.show_doc_to_all = log.show_doc_to_all
                        personal_log.category_id = log.category_id
                        self.pg_session.add(personal_log)
                        await self.pg_session.flush()
                    else:
                        personal_log = PersonalIncomeLog(
                            family_id=family_id,
                            user_id=new_personal_savings_user_id,
                            logged_by=logged_by_user_id,
                            income_name=log.income_name,
                            amount=new_personal_savings_amount,
                            income_date=log.income_date,
                            family_amount=log.family_amount,
                            family_income_log_id=log.id,
                            source_type="FAMILY_INCOME_LOG",
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

            # Sync per-user doc access (None = untouched)
            if data.doc_viewer_user_ids is not None:
                await self._sync_income_log_doc_access(log.id, data.doc_viewer_user_ids)

            show_breakdown = (
                data.show_funding_to_family
                if data.show_funding_to_family is not None
                else log.show_funding_to_family
            )
            await sync_log_funding_breakdown(
                self.pg_session,
                entity_type=ENTITY_FAMILY_INCOME_LOG,
                entity_id=log.id,
                host_family_id=family_id,
                show_to_family=show_breakdown,
                direction=LEDGER_IN,
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
    # Doc access helpers — recurring income
    # ------------------------------------------------------------------

    async def _get_recurring_income_doc_viewers(self, income_id: UUID) -> list[UUID]:
        """Return list of user_ids who have explicit doc view access for a recurring income."""
        stmt = select(RecurringIncomeDocAccess.user_id).where(
            RecurringIncomeDocAccess.income_id == income_id
        )
        result = await self.pg_session.execute(stmt)
        return list(result.scalars().all())

    async def _sync_recurring_income_doc_access(
        self,
        income_id: UUID,
        viewer_user_ids: list[UUID],
    ) -> None:
        """Replace the doc access rows for a recurring income with the given user list.

        Deletes all existing rows and inserts fresh ones in a single flush.
        """
        # Delete existing access rows
        await self.pg_session.execute(
            delete(RecurringIncomeDocAccess).where(
                RecurringIncomeDocAccess.income_id == income_id
            )
        )
        await self.pg_session.flush()

        # Insert new access rows (deduplicated)
        seen: set[UUID] = set()
        for user_id in viewer_user_ids:
            if user_id in seen:
                continue
            seen.add(user_id)
            self.pg_session.add(RecurringIncomeDocAccess(income_id=income_id, user_id=user_id))

        await self.pg_session.flush()

    # ------------------------------------------------------------------
    # Doc access helpers — income log
    # ------------------------------------------------------------------

    async def _get_income_log_doc_viewers(self, log_id: UUID) -> list[UUID]:
        """Return list of user_ids who have explicit doc view access for an income log."""
        stmt = select(FamilyIncomeLogDocAccess.user_id).where(
            FamilyIncomeLogDocAccess.log_id == log_id
        )
        result = await self.pg_session.execute(stmt)
        return list(result.scalars().all())

    async def _sync_income_log_doc_access(
        self,
        log_id: UUID,
        viewer_user_ids: list[UUID],
    ) -> None:
        """Replace the doc access rows for an income log with the given user list."""
        await self.pg_session.execute(
            delete(FamilyIncomeLogDocAccess).where(
                FamilyIncomeLogDocAccess.log_id == log_id
            )
        )
        await self.pg_session.flush()

        seen: set[UUID] = set()
        for user_id in viewer_user_ids:
            if user_id in seen:
                continue
            seen.add(user_id)
            self.pg_session.add(FamilyIncomeLogDocAccess(log_id=log_id, user_id=user_id))

        await self.pg_session.flush()

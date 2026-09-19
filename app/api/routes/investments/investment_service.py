"""Investment service (Plan 04)."""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Sequence, Optional
from uuid import UUID

from sqlalchemy import select, func, or_, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.investments.investment_schemas import (
    CreateInvestmentRequest,
    UpdateInvestmentRequest,
)
from app.api.routes.investments.model import FamilyInvestment, PersonalInvestment, InvestmentTxn
from app.api.routes.scheduler.model import ScheduledJob
from app.api.schemas.pagination import PaginationParams
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    LEDGER_IN,
    LEDGER_OUT,
)
from app.core.funding_service import FundingService, SplitLine
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.scope import ScopeContext, filter_entity_rows
from app.core.transfer_pools import scope_to_pool

logger = logging.getLogger(__name__)

SOURCE_FAMILY_INVESTMENT = "FAMILY_INVESTMENT"
SOURCE_PERSONAL_INVESTMENT = "PERSONAL_INVESTMENT"


def _source_type(inv: FamilyInvestment | PersonalInvestment) -> str:
    return SOURCE_PERSONAL_INVESTMENT if isinstance(inv, PersonalInvestment) else SOURCE_FAMILY_INVESTMENT


class InvestmentService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_investments(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = None,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[FamilyInvestment | PersonalInvestment, bool]], int]:
        fam_stmt = select(FamilyInvestment).where(FamilyInvestment.family_id == family_id)
        per_stmt = select(PersonalInvestment).where(PersonalInvestment.family_id == family_id)
        if status:
            fam_stmt = fam_stmt.where(FamilyInvestment.status == status)
            per_stmt = per_stmt.where(PersonalInvestment.status == status)
        family_rows = list((await self.pg_session.execute(fam_stmt)).scalars().all())
        personal_rows = list((await self.pg_session.execute(per_stmt)).scalars().all())
        combined = [(i, False) for i in family_rows] + [(i, True) for i in personal_rows]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].created_at, reverse=True)
        total = len(combined)
        return combined[pagination.offset : pagination.offset + pagination.page_size], total

    async def list_personal_investments(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = None,
    ) -> tuple[list[PersonalInvestment], int, Decimal, Decimal]:
        stmt = select(PersonalInvestment).where(PersonalInvestment.user_id == user_id)
        if status:
            stmt = stmt.where(PersonalInvestment.status == status)
        rows = list((await self.pg_session.execute(stmt)).scalars().all())
        rows.sort(key=lambda i: i.created_at, reverse=True)
        active = [r for r in rows if r.status == "ACTIVE"]
        invested_total = sum((i.invested_amount for i in active), Decimal("0"))
        current_total = sum((i.current_value for i in active), Decimal("0"))
        total = len(rows)
        page = rows[pagination.offset : pagination.offset + pagination.page_size]
        return page, total, invested_total, current_total

    async def get_personal_investment(
        self, investment_id: UUID, user_id: UUID
    ) -> PersonalInvestment | None:
        return (
            await self.pg_session.execute(
                select(PersonalInvestment).where(
                    PersonalInvestment.id == investment_id,
                    PersonalInvestment.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def create_personal_investment(
        self, user_id: UUID, family_id: UUID, request: CreateInvestmentRequest
    ) -> PersonalInvestment:
        inv, _ = await self.create_investment(
            family_id, user_id, request.model_copy(update={"isPersonal": True})
        )
        return inv  # type: ignore[return-value]

    async def upsert_split_plan(
        self, inv: FamilyInvestment | PersonalInvestment, split_lines: list[dict]
    ) -> None:
        from app.core.funding_service import FundingService as _FS

        await _FS(self.pg_session).save_split_plan(_source_type(inv), inv.id, split_lines)
        await self.pg_session.commit()

    async def create_investment(
        self, family_id: UUID, user_id: UUID, request: CreateInvestmentRequest
    ) -> tuple[FamilyInvestment | PersonalInvestment, bool]:
        common = dict(
            investment_name=request.investmentName,
            type=request.type,
            return_type=request.returnType,
            annual_return_rate=float(request.annualReturnRate) if request.annualReturnRate is not None else None,
            compounding_frequency=request.compoundingFrequency,
            has_recurring=request.hasRecurring,
            contribution_amount=request.contributionAmount,
            contribution_every=request.contributionEvery,
            next_contribution_date=request.nextContributionDate,
            tenure_months=request.tenureMonths,
            requires_confirmation=request.requiresConfirmation,
            maturity_date=request.maturityDate,
            maturity_amount=request.maturityAmount,
            auto_credit_on_maturity=request.autoCreditOnMaturity,
            document_id=request.documentId,
        )
        if request.isPersonal:
            inv = PersonalInvestment(
                family_id=family_id,
                user_id=user_id,
                access_level=request.accessLevel or "PRIVATE",
                **common,
            )
            is_personal = True
        else:
            inv = FamilyInvestment(
                family_id=family_id,
                in_someone_name=request.inSomeoneName or user_id,
                access_level=request.accessLevel or "FAMILY",
                **common,
            )
            is_personal = False

        self.pg_session.add(inv)
        await self.pg_session.flush()

        if request.initialLumpSum and request.initialLumpSum > 0:
            split_lines = None
            if request.splitLines:
                split_lines = [
                    SplitLine(pool_type=s.poolType, family_id=s.familyId, amount=s.amount)
                    for s in request.splitLines
                ]
            await contribute(
                self.pg_session,
                inv,
                request.initialLumpSum,
                split_lines,
                "Initial lump sum",
                txn_type="LUMP_SUM",
            )

        from app.scheduler.investment_cron import create_or_replace_next_contrib_job

        await create_or_replace_next_contrib_job(self.pg_session, inv, _source_type(inv))
        await self.pg_session.commit()
        await self.pg_session.refresh(inv)
        return inv, is_personal

    async def get_investment(
        self, investment_id: UUID, family_id: UUID
    ) -> tuple[FamilyInvestment | PersonalInvestment, bool] | None:
        for model, is_personal in ((FamilyInvestment, False), (PersonalInvestment, True)):
            row = (
                await self.pg_session.execute(
                    select(model).where(model.id == investment_id, model.family_id == family_id)
                )
            ).scalar_one_or_none()
            if row:
                return row, is_personal
        return None

    async def update_investment(
        self, inv: FamilyInvestment | PersonalInvestment, request: UpdateInvestmentRequest
    ) -> FamilyInvestment | PersonalInvestment:
        field_map = {
            "investmentName": "investment_name",
            "type": "type",
            "inSomeoneName": "in_someone_name",
            "returnType": "return_type",
            "annualReturnRate": "annual_return_rate",
            "compoundingFrequency": "compounding_frequency",
            "hasRecurring": "has_recurring",
            "contributionAmount": "contribution_amount",
            "contributionEvery": "contribution_every",
            "nextContributionDate": "next_contribution_date",
            "tenureMonths": "tenure_months",
            "requiresConfirmation": "requires_confirmation",
            "maturityDate": "maturity_date",
            "maturityAmount": "maturity_amount",
            "autoCreditOnMaturity": "auto_credit_on_maturity",
            "documentId": "document_id",
            "accessLevel": "access_level",
        }
        for camel, value in request.model_dump(exclude_none=True).items():
            attr = field_map.get(camel)
            if attr:
                setattr(inv, attr, value)

        source_type = _source_type(inv)
        if inv.status == "ACTIVE" and inv.has_recurring and inv.next_contribution_date:
            from app.scheduler.investment_cron import create_or_replace_next_contrib_job

            await create_or_replace_next_contrib_job(self.pg_session, inv, source_type)
        else:
            await self.pg_session.execute(
                sa_update(ScheduledJob)
                .where(
                    ScheduledJob.source_type == source_type,
                    ScheduledJob.source_id == inv.id,
                    ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
                )
                .values(status=JOB_STATUS_CANCELLED)
            )

        await self.pg_session.commit()
        await self.pg_session.refresh(inv)
        return inv

    async def delete_investment(self, inv: FamilyInvestment | PersonalInvestment) -> None:
        source_type = _source_type(inv)
        await self.pg_session.execute(
            sa_update(ScheduledJob)
            .where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == inv.id,
                ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
            )
            .values(status=JOB_STATUS_CANCELLED)
        )
        inv.status = "CANCELLED"
        inv.completed_at = datetime.now(timezone.utc)
        await self.pg_session.commit()

    async def list_txns(
        self, inv: FamilyInvestment | PersonalInvestment
    ) -> list[InvestmentTxn]:
        stmt = (
            select(InvestmentTxn)
            .where(InvestmentTxn.investment_id == inv.id)
            .order_by(InvestmentTxn.occurred_at.desc())
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def update_value(
        self, inv: FamilyInvestment | PersonalInvestment, new_value: Decimal
    ) -> FamilyInvestment | PersonalInvestment:
        delta = new_value - (inv.current_value or Decimal("0"))
        inv.current_value = new_value
        self.pg_session.add(
            InvestmentTxn(
                investment_scope="PERSONAL" if isinstance(inv, PersonalInvestment) else "FAMILY",
                investment_id=inv.id,
                txn_type="VALUE_ADJUST",
                amount=abs(delta),
                direction="IN" if delta >= 0 else "OUT",
                occurred_at=datetime.now(timezone.utc),
                source_type="MANUAL",
            )
        )
        await self.pg_session.commit()
        await self.pg_session.refresh(inv)
        return inv


async def contribute(
    session: AsyncSession,
    inv: FamilyInvestment | PersonalInvestment,
    amount: Decimal,
    split_lines: list[SplitLine] | None = None,
    note: str | None = None,
    paid_externally: bool = False,
    is_scheduled: bool = False,
    txn_type: str = "CONTRIBUTION",
) -> InvestmentTxn:
    when = datetime.now(timezone.utc)
    is_personal = isinstance(inv, PersonalInvestment)
    source_type = SOURCE_PERSONAL_INVESTMENT if is_personal else SOURCE_FAMILY_INVESTMENT

    if not paid_externally:
        if split_lines:
            fs = FundingService(session)
            await fs.execute_debit(
                split_lines,
                amount,
                ledger_source_type="INVESTMENT_CONTRIB",
                entity_type=source_type,
                entity_id=inv.id,
                description=f"Investment contrib — {inv.investment_name}",
                occurred_at=when,
            )
        else:
            pool = scope_to_pool(
                "PERSONAL" if is_personal else "FAMILY",
                family_id=inv.family_id,
                user_id=getattr(inv, "user_id", None) if is_personal else None,
            )
            ledger = SavingsLedgerService(session)
            await ledger.apply_movement(
                pool,
                amount,
                LEDGER_OUT,
                "INVESTMENT_CONTRIB",
                source_id=inv.id,
                description=f"Investment contrib — {inv.investment_name}",
                occurred_at=when,
            )

    inv.invested_amount += amount
    inv.current_value = (inv.current_value or Decimal("0")) + amount

    txn = InvestmentTxn(
        investment_scope="PERSONAL" if is_personal else "FAMILY",
        investment_id=inv.id,
        txn_type=txn_type,
        amount=amount,
        direction="IN",
        occurred_at=when,
        source_type="SCHEDULED" if is_scheduled else "MANUAL",
        note=note,
    )
    session.add(txn)
    await session.flush()
    return txn


async def redeem(
    session: AsyncSession,
    inv: FamilyInvestment | PersonalInvestment,
    amount: Decimal,
    note: str | None = None,
    *,
    credit_pool: str = "FAMILY",
    user_id: UUID | None = None,
) -> InvestmentTxn:
    """Withdraw from investment into the savings pool."""
    if amount > (inv.current_value or Decimal("0")):
        raise ValueError("Cannot redeem more than current value")

    when = datetime.now(timezone.utc)
    is_personal = isinstance(inv, PersonalInvestment)
    use_personal_pool = is_personal or credit_pool == "PERSONAL"

    pool = scope_to_pool(
        "PERSONAL" if use_personal_pool else "FAMILY",
        family_id=inv.family_id,
        user_id=getattr(inv, "user_id", None) if use_personal_pool else None,
    )
    ledger = SavingsLedgerService(session)
    await ledger.apply_movement(
        pool,
        amount,
        LEDGER_IN,
        "INVESTMENT_REDEEM",
        source_id=inv.id,
        description=f"Investment redemption — {inv.investment_name}",
        occurred_at=when,
    )

    income_name = f"Investment redemption — {inv.investment_name}"
    if is_personal:
        from app.api.routes.family_income.model import PersonalIncomeLog

        session.add(
            PersonalIncomeLog(
                family_id=inv.family_id,
                user_id=inv.user_id,
                logged_by=inv.user_id,
                income_name=income_name,
                amount=amount,
                income_date=when,
                source_type="INVESTMENT_REDEEM",
                source_id=inv.id,
            )
        )
    else:
        from app.api.routes.family_income.model import FamilyIncomeLog

        actor = user_id or getattr(inv, "in_someone_name", None)
        if actor is None:
            raise ValueError("Cannot determine user for income log")
        session.add(
            FamilyIncomeLog(
                family_id=inv.family_id,
                scope_type="FAMILY",
                logged_by=actor,
                income_name=income_name,
                total_amount=amount,
                family_amount=amount,
                income_date=when,
                source_type="INVESTMENT_REDEEM",
                source_id=inv.id,
                added_by_user_id=actor,
            )
        )

    # We assume proportional reduction of invested amount for simplicity
    # if full redemption, zero out everything.
    if amount == inv.current_value:
        inv.invested_amount = Decimal("0")
        inv.current_value = Decimal("0")
        inv.status = "CLOSED"
        inv.completed_at = when
    else:
        ratio = Decimal("1") - (amount / inv.current_value)
        inv.invested_amount = inv.invested_amount * ratio
        inv.current_value -= amount

    txn = InvestmentTxn(
        investment_scope="PERSONAL" if is_personal else "FAMILY",
        investment_id=inv.id,
        txn_type="REDEMPTION",
        amount=amount,
        direction="OUT",
        occurred_at=when,
        source_type="MANUAL",
        note=note,
    )
    session.add(txn)
    
    if inv.status == "CLOSED":
        # cancel scheduled jobs
        source_type = SOURCE_PERSONAL_INVESTMENT if is_personal else SOURCE_FAMILY_INVESTMENT
        from app.api.routes.scheduler.model import ScheduledJob
        from sqlalchemy import update
        await session.execute(
            update(ScheduledJob)
            .where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == inv.id,
                ScheduledJob.status.in_(["SCHEDULED", "AWAITING_CONFIRMATION"])
            )
            .values(status="CANCELLED")
        )

    await session.flush()
    return txn

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.insurance.insurance_schemas import (
    InsuranceCreateRequest,
    InsuranceUpdateRequest,
)
from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.schemas.pagination import PaginationParams
from app.core.scope import ScopeContext, filter_entity_rows

SOURCE_FAMILY_INSURANCE = "FAMILY_INSURANCE"
SOURCE_PERSONAL_INSURANCE = "PERSONAL_INSURANCE"


def _source_type(ins: FamilyInsurance | PersonalInsurance) -> str:
    return SOURCE_PERSONAL_INSURANCE if isinstance(ins, PersonalInsurance) else SOURCE_FAMILY_INSURANCE


class InsuranceService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_insurances(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[object, bool]], int]:
        family_rows = list(
            (await self.pg_session.execute(
                select(FamilyInsurance).where(FamilyInsurance.family_id == family_id)
            )).scalars().all()
        )
        personal_rows = list(
            (await self.pg_session.execute(
                select(PersonalInsurance).where(PersonalInsurance.family_id == family_id)
            )).scalars().all()
        )
        combined = [(i, False) for i in family_rows] + [(i, True) for i in personal_rows]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].created_at, reverse=True)
        total = len(combined)
        return combined[pagination.offset : pagination.offset + pagination.page_size], total

    async def _link_premium_expense(
        self,
        ins: FamilyInsurance | PersonalInsurance,
        user_id: UUID,
        request: InsuranceCreateRequest,
        is_personal: bool,
    ) -> None:
        freq = (request.premium_every or "").upper()
        if not freq or freq == "ONE_TIME":
            return
        from decimal import Decimal
        from datetime import datetime, timezone

        from app.api.routes.family.model import Family
        from app.api.routes.money.model import FosMoneyRule, FosMoneyRuleParty
        from app.core.tz_eighteen import at_eighteen_utc

        emi_count = request.emi_count
        total = Decimal(str(request.premium_amount or 0))
        if emi_count and emi_count > 0 and total > 0:
            emi_amt = (total / Decimal(emi_count)).quantize(Decimal("0.01"))
        elif total > 0:
            emi_amt = total
        else:
            return
        tz = "Asia/Kolkata"
        if not is_personal:
            fam = await self.pg_session.get(Family, ins.family_id)
            if fam is not None and getattr(fam, "timezone", None):
                tz = fam.timezone
        next_at = request.next_premium_date or datetime.now(timezone.utc)
        rule = FosMoneyRule(
            scope="PERSONAL" if is_personal else "FAMILY",
            family_id=None if is_personal else ins.family_id,
            owner_user_id=user_id if is_personal else None,
            kind="EXPENSE",
            name=f"{ins.insurance_name} premium",
            amount=emi_amt,
            frequency=freq,
            next_run_at=at_eighteen_utc(next_at, tz),
            let_everyone_edit=False if is_personal else bool(request.let_everyone_edit),
            created_by=user_id,
            insurance_id=ins.id,
            emi_remaining=emi_count,
            status="ACTIVE",
        )
        self.pg_session.add(rule)
        await self.pg_session.flush()
        self.pg_session.add(
            FosMoneyRuleParty(
                rule_id=rule.id,
                party_type="FAMILY" if not is_personal else "MEMBER",
                user_id=user_id if is_personal else None,
            )
        )
        ins.premium_amount = emi_amt

    async def create_insurance(
        self, family_id: UUID, user_id: UUID, request: InsuranceCreateRequest
    ) -> tuple[FamilyInsurance | PersonalInsurance, bool]:
        common = dict(
            insurance_name=request.insurance_name,
            type=request.type,
            provider=request.provider,
            policy_number=request.policy_number,
            nominee=request.nominee,
            premium_amount=request.premium_amount,
            coverage_amount=request.coverage_amount,
            premium_every=request.premium_every,
            next_premium_date=request.next_premium_date,
            start_date=request.start_date,
            end_date=request.end_date,
            maturity_date=request.maturity_date,
            maturity_amount=request.maturity_amount,
            requires_confirmation=False,
            bounce_fine_amount=0,
            allow_auto_lapse=False,
            insured_user_id=request.insured_user_id,
            document_id=request.document_id,
        )
        if request.is_personal:
            ins = PersonalInsurance(
                family_id=family_id,
                user_id=user_id,
                scope_type=request.scope_type,
                access_level=request.access_level or "PRIVATE",
                insured_member=request.insured_user_id or user_id,
                **common,
            )
            is_personal = True
        else:
            ins = FamilyInsurance(
                family_id=family_id,
                scope_type=request.scope_type,
                access_level=request.access_level or "FAMILY",
                insured_member=request.insured_user_id or user_id,
                **common,
            )
            is_personal = False

        self.pg_session.add(ins)
        await self.pg_session.flush()
        await self._link_premium_expense(ins, user_id, request, is_personal)
        await self.pg_session.commit()
        await self.pg_session.refresh(ins)
        return ins, is_personal

    async def list_personal_insurances(
        self, user_id: UUID, pagination: PaginationParams
    ) -> tuple[list[PersonalInsurance], int]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalInsurance).where(PersonalInsurance.user_id == user_id)
                )
            ).scalars().all()
        )
        rows.sort(key=lambda x: x.created_at, reverse=True)
        total = len(rows)
        return rows[pagination.offset : pagination.offset + pagination.page_size], total

    async def get_personal_insurance(
        self, insurance_id: UUID, user_id: UUID
    ) -> PersonalInsurance | None:
        return (
            await self.pg_session.execute(
                select(PersonalInsurance).where(
                    PersonalInsurance.id == insurance_id,
                    PersonalInsurance.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def create_personal_insurance(
        self, user_id: UUID, family_id: UUID, request: InsuranceCreateRequest
    ) -> PersonalInsurance:
        ins, _ = await self.create_insurance(
            family_id,
            user_id,
            request.model_copy(update={"is_personal": True}),
        )
        return ins  # type: ignore[return-value]

    async def get_insurance(
        self, insurance_id: UUID, family_id: UUID
    ) -> tuple[FamilyInsurance | PersonalInsurance, bool] | None:
        for model, is_personal in ((FamilyInsurance, False), (PersonalInsurance, True)):
            row = (await self.pg_session.execute(
                select(model).where(model.id == insurance_id, model.family_id == family_id)
            )).scalar_one_or_none()
            if row:
                return row, is_personal
        return None

    async def update_insurance(
        self, ins: FamilyInsurance | PersonalInsurance, request: InsuranceUpdateRequest
    ) -> FamilyInsurance | PersonalInsurance:
        data = request.model_dump(exclude_none=True, exclude={"splitLines"})
        for field, value in data.items():
            setattr(ins, field, value)

        await self.pg_session.commit()
        await self.pg_session.refresh(ins)
        return ins

    async def upsert_split_plan(
        self, ins: FamilyInsurance | PersonalInsurance, split_lines: list[dict]
    ) -> None:
        from app.core.funding_service import FundingService

        await FundingService(self.pg_session).save_split_plan(
            _source_type(ins),
            ins.id,
            split_lines,
        )
        await self.pg_session.commit()

    async def delete_insurance(self, ins: FamilyInsurance | PersonalInsurance) -> None:
        from app.api.routes.money.model import FosMoneyRule

        rules = list(
            (
                await self.pg_session.execute(
                    select(FosMoneyRule).where(FosMoneyRule.insurance_id == ins.id)
                )
            ).scalars().all()
        )
        for rule in rules:
            rule.status = "CANCELLED"
        ins.status = "CANCELLED"
        await self.pg_session.commit()

    async def pay_now(
        self,
        ins: FamilyInsurance | PersonalInsurance,
        *,
        split_lines: list | None = None,
        paid_externally: bool = False,
    ) -> FamilyInsurance | PersonalInsurance:
        raise ValueError("Pay now is removed. Insurance premiums apply via the mapped recurring expense.")

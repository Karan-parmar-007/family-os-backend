from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, literal, or_, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.category.category_service import CategoryService
from app.api.routes.family.model import Family
from app.api.routes.insurance.insurance_schemas import (
    InsuranceCreateRequest,
    InsuranceUpdateRequest,
    _ScheduleFields,
)
from app.api.routes.insurance.model import (
    FamilyInsurance,
    FosInsuranceInstallment,
    PersonalInsurance,
)
from app.api.routes.profile.model import FosProfile
from app.api.schemas.pagination import PaginationParams
from app.core.scope import ScopeContext
from app.core.tz_eighteen import at_eighteen_utc, local_date, step_eighteen_utc

Policy = FamilyInsurance | PersonalInsurance

PERIODS_PER_YEAR = {"MONTHLY": 12, "QUARTERLY": 4, "HALF_YEARLY": 2, "YEARLY": 1}
UNCATEGORIZED = "Uncategorized"
CENT = Decimal("0.01")


def split_annual(annual: Decimal, periods: int) -> list[Decimal]:
    """Even split; the last payment absorbs rounding so the year sums exactly."""
    base = (annual / periods).quantize(CENT, rounding=ROUND_DOWN)
    return [base] * (periods - 1) + [annual - base * (periods - 1)]


class InsuranceService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    # --- helpers ---

    async def policy_tz(self, ins: Policy) -> str:
        if isinstance(ins, PersonalInsurance):
            profile = await self.pg_session.get(FosProfile, ins.user_id)
            return profile.timezone if profile else "Asia/Kolkata"
        fam = await self.pg_session.get(Family, ins.family_id)
        return fam.timezone if fam and fam.timezone else "Asia/Kolkata"

    async def _category_name(self, category_id: UUID | None, *, user_id: UUID, is_personal: bool, family_id: UUID) -> str:
        cat = await CategoryService(self.pg_session).require_usable(
            category_id,
            user_id=user_id,
            scope="PERSONAL" if is_personal else "FAMILY",
            family_id=None if is_personal else family_id,
            category_type="INSURANCE",
        )
        return cat.name if cat else UNCATEGORIZED

    async def generate_interval_year(self, ins: Policy, first_due: datetime, tz: str) -> None:
        """Add one policy year of installments starting at ``first_due``."""
        freq = ins.premium_every or "YEARLY"
        periods = PERIODS_PER_YEAR[freq]
        anchor = local_date(first_due, tz).day
        due = first_due
        for amount in split_annual(Decimal(str(ins.annual_premium)), periods):
            if ins.end_date is not None and due > ins.end_date:
                break
            self.pg_session.add(
                FosInsuranceInstallment(
                    insurance_id=ins.id,
                    is_personal=isinstance(ins, PersonalInsurance),
                    due_at=due,
                    amount=amount,
                )
            )
            due = step_eighteen_utc(due, tz, freq, anchor_day=anchor)
        await self.pg_session.flush()

    async def _cancel_pending(self, ins: Policy) -> None:
        await self.pg_session.execute(
            update(FosInsuranceInstallment)
            .where(
                FosInsuranceInstallment.insurance_id == ins.id,
                FosInsuranceInstallment.status == "PENDING",
            )
            .values(status="CANCELLED")
        )

    async def _cancel_legacy_rules(self, ins: Policy) -> None:
        from app.api.routes.money.model import FosMoneyRule

        await self.pg_session.execute(
            update(FosMoneyRule)
            .where(FosMoneyRule.insurance_id == ins.id, FosMoneyRule.status.in_(("ACTIVE", "PAUSED")))
            .values(status="CANCELLED")
        )

    async def refresh_next_due(self, ins: Policy) -> None:
        nxt = (
            await self.pg_session.execute(
                select(FosInsuranceInstallment)
                .where(
                    FosInsuranceInstallment.insurance_id == ins.id,
                    FosInsuranceInstallment.status == "PENDING",
                )
                .order_by(FosInsuranceInstallment.due_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        ins.next_premium_date = nxt.due_at if nxt else None

    async def apply_schedule(self, ins: Policy, req: _ScheduleFields) -> None:
        """Replace future installments with the requested schedule (paid ones stay)."""
        mode = req.schedule_mode or ins.schedule_mode
        await self._cancel_pending(ins)
        await self._cancel_legacy_rules(ins)
        await self.pg_session.flush()
        tz = await self.policy_tz(ins)
        ins.schedule_mode = mode
        if mode == "INTERVAL":
            ins.annual_premium = req.annual_premium or ins.annual_premium
            ins.premium_every = req.premium_every or ins.premium_every
            first = at_eighteen_utc(req.next_premium_date or ins.next_premium_date, tz)
            ins.premium_amount = split_annual(Decimal(str(ins.annual_premium)), PERIODS_PER_YEAR[ins.premium_every])[0]
            await self.generate_interval_year(ins, first, tz)
        elif mode == "CUSTOM":
            ins.annual_premium = None
            ins.premium_every = None
            total = Decimal("0")
            for item in sorted(req.installments or [], key=lambda i: i.due_date):
                total += item.amount
                self.pg_session.add(
                    FosInsuranceInstallment(
                        insurance_id=ins.id,
                        is_personal=isinstance(ins, PersonalInsurance),
                        due_at=at_eighteen_utc(item.due_date, tz),
                        amount=item.amount,
                    )
                )
            ins.premium_amount = total
            await self.pg_session.flush()
        else:
            ins.annual_premium = None
            ins.premium_every = None
        await self.refresh_next_due(ins)

    # --- reads ---

    def _visible(self, family_id: UUID, user_id: UUID):
        fam = and_(
            FamilyInsurance.family_id == family_id,
            FamilyInsurance.status != "CANCELLED",
            or_(
                FamilyInsurance.access_level == "FAMILY",
                FamilyInsurance.insured_member == user_id,
                FamilyInsurance.created_by == user_id,
            ),
        )
        per = and_(
            PersonalInsurance.family_id == family_id,
            PersonalInsurance.status != "CANCELLED",
            or_(PersonalInsurance.user_id == user_id, PersonalInsurance.access_level == "FAMILY"),
        )
        return fam, per

    async def _load(self, ids: list[tuple[UUID, bool]]) -> list[tuple[Policy, bool]]:
        found: dict[UUID, Policy] = {}
        for model, personal in ((FamilyInsurance, False), (PersonalInsurance, True)):
            wanted = [i for i, p in ids if p is personal]
            if wanted:
                for row in (await self.pg_session.execute(select(model).where(model.id.in_(wanted)))).scalars():
                    found[row.id] = row
        return [(found[i], p) for i, p in ids if i in found]

    async def list_insurances(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext,
    ) -> tuple[list[tuple[Policy, bool]], int]:
        fam_where, per_where = self._visible(family_id, scope_ctx.user_id)
        combined = union_all(
            select(FamilyInsurance.id.label("id"), literal(False).label("p"), FamilyInsurance.created_at.label("t")).where(fam_where),
            select(PersonalInsurance.id.label("id"), literal(True).label("p"), PersonalInsurance.created_at.label("t")).where(per_where),
        ).subquery()
        total = (await self.pg_session.execute(select(func.count()).select_from(combined))).scalar_one()
        page = (
            await self.pg_session.execute(
                select(combined.c.id, combined.c.p)
                .order_by(combined.c.t.desc(), combined.c.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).all()
        return await self._load([(r.id, r.p) for r in page]), total

    async def list_personal_insurances(
        self, user_id: UUID, pagination: PaginationParams
    ) -> tuple[list[PersonalInsurance], int]:
        where = [PersonalInsurance.user_id == user_id, PersonalInsurance.status != "CANCELLED"]
        total = (await self.pg_session.execute(select(func.count()).select_from(PersonalInsurance).where(*where))).scalar_one()
        rows = (
            await self.pg_session.execute(
                select(PersonalInsurance)
                .where(*where)
                .order_by(PersonalInsurance.created_at.desc(), PersonalInsurance.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def installment_summary(self, ids: list[UUID]) -> dict[UUID, dict]:
        if not ids:
            return {}
        rows = (
            await self.pg_session.execute(
                select(
                    FosInsuranceInstallment.insurance_id,
                    func.count().filter(FosInsuranceInstallment.status == "PAID"),
                    func.count().filter(FosInsuranceInstallment.status == "PENDING"),
                )
                .where(FosInsuranceInstallment.insurance_id.in_(ids))
                .group_by(FosInsuranceInstallment.insurance_id)
            )
        ).all()
        nxt = (
            await self.pg_session.execute(
                select(FosInsuranceInstallment.insurance_id, FosInsuranceInstallment.amount)
                .where(
                    FosInsuranceInstallment.insurance_id.in_(ids),
                    FosInsuranceInstallment.status == "PENDING",
                )
                .distinct(FosInsuranceInstallment.insurance_id)
                .order_by(FosInsuranceInstallment.insurance_id, FosInsuranceInstallment.due_at)
            )
        ).all()
        out = {r[0]: {"paid_count": r[1], "pending_count": r[2]} for r in rows}
        for ins_id, amount in nxt:
            out.setdefault(ins_id, {})["next_installment_amount"] = amount
        return out

    async def list_installments(self, ins: Policy) -> list[FosInsuranceInstallment]:
        rows = (
            await self.pg_session.execute(
                select(FosInsuranceInstallment)
                .where(
                    FosInsuranceInstallment.insurance_id == ins.id,
                    FosInsuranceInstallment.status != "CANCELLED",
                )
                .order_by(FosInsuranceInstallment.due_at)
            )
        ).scalars().all()
        return list(rows)

    async def get_personal_insurance(self, insurance_id: UUID, user_id: UUID) -> PersonalInsurance | None:
        return (
            await self.pg_session.execute(
                select(PersonalInsurance).where(
                    PersonalInsurance.id == insurance_id,
                    PersonalInsurance.user_id == user_id,
                    PersonalInsurance.status != "CANCELLED",
                )
            )
        ).scalar_one_or_none()

    async def get_insurance(self, insurance_id: UUID, family_id: UUID) -> tuple[Policy, bool] | None:
        for model, is_personal in ((FamilyInsurance, False), (PersonalInsurance, True)):
            row = (
                await self.pg_session.execute(
                    select(model).where(
                        model.id == insurance_id,
                        model.family_id == family_id,
                        model.status != "CANCELLED",
                    )
                )
            ).scalar_one_or_none()
            if row:
                return row, is_personal
        return None

    # --- writes ---

    async def create_insurance(
        self, family_id: UUID, user_id: UUID, request: InsuranceCreateRequest
    ) -> tuple[Policy, bool]:
        is_personal = request.is_personal
        type_name = (request.type or "").strip() or await self._category_name(
            request.category_id, user_id=user_id, is_personal=is_personal, family_id=family_id
        )
        common = dict(
            family_id=family_id,
            insurance_name=request.insurance_name.strip(),
            type=type_name,
            category_id=request.category_id,
            provider=request.provider,
            policy_number=request.policy_number,
            nominee=request.nominee,
            premium_amount=request.premium_amount,
            coverage_amount=request.coverage_amount,
            start_date=request.start_date,
            end_date=request.end_date,
            maturity_date=request.maturity_date,
            maturity_amount=request.maturity_amount,
            requires_confirmation=False,
            bounce_fine_amount=0,
            allow_auto_lapse=False,
            insured_user_id=request.insured_user_id,
            insured_member=request.insured_user_id or user_id,
            document_id=request.document_id,
        )
        if is_personal:
            ins: Policy = PersonalInsurance(
                user_id=user_id,
                scope_type="PERSONAL",
                access_level=request.access_level if request.access_level in {"PRIVATE", "FAMILY"} else "PRIVATE",
                **common,
            )
        else:
            ins = FamilyInsurance(
                scope_type="FAMILY",
                access_level=request.access_level or "FAMILY",
                created_by=user_id,
                let_everyone_edit=request.let_everyone_edit,
                **common,
            )
        self.pg_session.add(ins)
        await self.pg_session.flush()
        await self.apply_schedule(ins, request)
        await self.pg_session.commit()
        await self.pg_session.refresh(ins)
        return ins, is_personal

    async def create_personal_insurance(
        self, user_id: UUID, family_id: UUID, request: InsuranceCreateRequest
    ) -> PersonalInsurance:
        ins, _ = await self.create_insurance(family_id, user_id, request.model_copy(update={"is_personal": True}))
        return ins  # type: ignore[return-value]

    async def update_insurance(
        self,
        ins: Policy,
        request: InsuranceUpdateRequest,
        *,
        actor_id: UUID,
        is_head: bool = False,
    ) -> Policy:
        is_personal = isinstance(ins, PersonalInsurance)
        data = request.model_dump(exclude_unset=True)
        schedule_keys = {"schedule_mode", "annual_premium", "premium_every", "next_premium_date", "installments"}
        schedule_changed = bool(schedule_keys & data.keys())
        for key in schedule_keys:
            data.pop(key, None)

        if "category_id" in data:
            ins.type = await self._category_name(
                data["category_id"], user_id=actor_id, is_personal=is_personal, family_id=ins.family_id
            )
            ins.category_id = data.pop("category_id")
        if "let_everyone_edit" in data:
            flag = bool(data.pop("let_everyone_edit"))
            if not is_personal and flag != ins.let_everyone_edit:
                if actor_id != ins.created_by and not is_head:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only the creator or a family head can change who may edit",
                    )
                ins.let_everyone_edit = flag
        if is_personal and data.get("access_level") not in (None, "PRIVATE", "FAMILY"):
            data["access_level"] = "PRIVATE"
        if "insured_user_id" in data:
            ins.insured_member = data["insured_user_id"] or ins.insured_member
        for field, value in data.items():
            if value is None and field in {"insurance_name", "coverage_amount", "premium_amount", "access_level", "status"}:
                continue
            setattr(ins, field, value)

        if schedule_changed:
            mode = request.schedule_mode or ins.schedule_mode
            if mode == "LEGACY":
                mode = "NONE"
            merged = _ScheduleFields(
                schedule_mode=mode,
                annual_premium=request.annual_premium or ins.annual_premium,
                premium_every=request.premium_every or ins.premium_every,
                next_premium_date=request.next_premium_date or ins.next_premium_date,
                installments=request.installments,
            )
            try:
                merged.check_schedule()
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
            await self.apply_schedule(ins, merged)
        elif ins.status != "ACTIVE":
            await self._cancel_pending(ins)
            await self.refresh_next_due(ins)

        await self.pg_session.commit()
        await self.pg_session.refresh(ins)
        return ins

    async def delete_insurance(self, ins: Policy) -> None:
        await self._cancel_pending(ins)
        await self._cancel_legacy_rules(ins)
        ins.status = "CANCELLED"
        ins.next_premium_date = None
        await self.pg_session.commit()

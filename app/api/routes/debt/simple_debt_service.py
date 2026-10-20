import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.api.routes.category.category_service import CategoryService
from app.api.routes.debt.simple_debt_models import FosDebt
from app.api.routes.debt.simple_debt_schemas import DebtCreateRequest, DebtUpdateRequest
from app.api.routes.family.model import Family
from app.api.routes.money.model import FosMoneyRule, FosMoneyRuleParty
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.pagination import PaginationParams
from app.core.date_advance import normalize_frequency
from app.core.scope import can_edit_shared
from app.core.tz_eighteen import at_eighteen_utc, local_date

logger = logging.getLogger(__name__)


class SimpleDebtService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def _check_family_membership(self, user_id: UUID, family_id: UUID) -> Tuple[bool, bool]:
        stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        link = (await self.pg_session.execute(stmt)).scalars().first()
        if not link:
            return False, False
        return True, link.is_family_manager

    async def _tz(self, scope: str, family_id: UUID | None, user_id: UUID) -> str:
        if scope == "FAMILY" and family_id:
            fam = await self.pg_session.get(Family, family_id)
            if fam is not None and fam.timezone:
                return fam.timezone
        profile = await self.pg_session.get(FosProfile, user_id)
        return profile.timezone if profile is not None else "Asia/Kolkata"

    async def can_edit(self, user_id: UUID, debt: FosDebt, *, is_head: bool | None = None) -> bool:
        if debt.scope == "PERSONAL":
            return debt.created_by == user_id
        if is_head is None:
            is_member, is_head = await self._check_family_membership(user_id, debt.family_id)
            if not is_member:
                return False
        return can_edit_shared(
            actor_id=user_id,
            creator_id=debt.created_by,
            is_head=is_head,
            let_everyone_edit=debt.let_everyone_edit,
        )

    async def _check_category(self, category_id: UUID | None, *, user_id: UUID, scope: str, family_id: UUID | None) -> None:
        await CategoryService(self.pg_session).require_usable(
            category_id, user_id=user_id, scope=scope, family_id=family_id, category_type="DEBT"
        )

    async def create_debt(self, user_id: UUID, req: DebtCreateRequest) -> FosDebt:
        scope = (req.scope or "FAMILY").upper()
        if scope == "FAMILY":
            if not req.family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required for FAMILY scope")
            is_member, _ = await self._check_family_membership(user_id, req.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this family")
        else:
            scope = "PERSONAL"
            req.family_id = None
            req.owner_type = "SELF"
            req.owner_user_id = user_id
        await self._check_category(req.category_id, user_id=user_id, scope=scope, family_id=req.family_id)

        amt = Decimal(str(req.amount))
        paid = min(amt, Decimal(str(req.amount_paid or 0)))
        debt_status = "SETTLED" if paid >= amt else "OPEN"

        debt = FosDebt(
            scope=scope,
            family_id=req.family_id,
            owner_type=req.owner_type,
            owner_user_id=req.owner_user_id,
            name=req.name.strip(),
            amount=amt,
            amount_paid=paid,
            has_emi=req.has_emi,
            add_emi_to_paid=req.add_emi_to_paid,
            category_id=req.category_id,
            document_id=req.document_id,
            let_everyone_edit=req.let_everyone_edit if scope == "FAMILY" else False,
            created_by=user_id,
            status=debt_status,
        )
        self.pg_session.add(debt)
        await self.pg_session.flush()

        if req.has_emi and req.emi_amount and req.emi_amount > 0 and debt_status == "OPEN":
            try:
                frequency = normalize_frequency(req.frequency)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
            tz = await self._tz(scope, req.family_id, user_id)
            first = at_eighteen_utc(req.next_emi_date or datetime.now(timezone.utc), tz)
            emi_rule = FosMoneyRule(
                scope=scope,
                family_id=req.family_id,
                owner_user_id=user_id if scope == "PERSONAL" else None,
                kind="EXPENSE",
                name=f"{debt.name} EMI",
                amount=Decimal(str(req.emi_amount)).quantize(Decimal("0.01")),
                frequency=frequency,
                every_n=req.every_n,
                anchor_day=local_date(first, tz).day,
                next_run_at=first,
                let_everyone_edit=debt.let_everyone_edit,
                created_by=user_id,
                debt_id=debt.id,
                status="ACTIVE",
            )
            self.pg_session.add(emi_rule)
            await self.pg_session.flush()
            self.pg_session.add(
                FosMoneyRuleParty(
                    rule_id=emi_rule.id,
                    party_type="MEMBER" if req.owner_type in ("MEMBER", "SELF") else "FAMILY",
                    user_id=req.owner_user_id if req.owner_type in ("MEMBER", "SELF") else None,
                )
            )
            debt.linked_rule_id = emi_rule.id

        await self.pg_session.commit()
        await self.pg_session.refresh(debt)
        return debt

    async def list_debts(
        self,
        user_id: UUID,
        scope: str,
        family_id: Optional[UUID] = None,
        status_filter: Optional[str] = None,
        *,
        pagination: PaginationParams,
        category_id: Optional[UUID] = None,
        q: Optional[str] = None,
    ) -> Tuple[List[FosDebt], int, bool]:
        """Returns (items, total, is_head)."""
        scope = (scope or "FAMILY").upper()
        is_head = False
        filters = [FosDebt.scope == scope]
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required")
            is_member, is_head = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this family")
            filters.append(FosDebt.family_id == family_id)
        else:
            filters.append(FosDebt.owner_user_id == user_id)

        if status_filter:
            filters.append(FosDebt.status == status_filter.upper())
        if category_id:
            filters.append(FosDebt.category_id == category_id)
        if q and q.strip():
            filters.append(func.lower(FosDebt.name).contains(q.strip().lower(), autoescape=True))

        total = (
            await self.pg_session.execute(select(func.count()).select_from(FosDebt).where(*filters))
        ).scalar_one()
        items = (
            await self.pg_session.execute(
                select(FosDebt)
                .where(*filters)
                .order_by(FosDebt.created_at.desc(), FosDebt.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return list(items), total, is_head

    async def _get_editable(self, user_id: UUID, debt_id: UUID) -> Tuple[FosDebt, bool]:
        debt = await self.pg_session.get(FosDebt, debt_id, with_for_update=True)
        if not debt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
        is_head = False
        if debt.scope == "FAMILY":
            is_member, is_head = await self._check_family_membership(user_id, debt.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this family")
        if not await self.can_edit(user_id, debt, is_head=is_head):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the creator or a family head can change this debt",
            )
        return debt, is_head

    async def _linked_rule(self, debt: FosDebt) -> FosMoneyRule | None:
        if not debt.linked_rule_id:
            return None
        return await self.pg_session.get(FosMoneyRule, debt.linked_rule_id)

    async def update_debt(self, user_id: UUID, debt_id: UUID, req: DebtUpdateRequest) -> FosDebt:
        debt, is_head = await self._get_editable(user_id, debt_id)
        sent = req.model_fields_set

        if req.name is not None:
            debt.name = req.name.strip()
        if req.amount is not None:
            debt.amount = Decimal(str(req.amount))
        if req.amount_paid is not None:
            debt.amount_paid = Decimal(str(req.amount_paid))
        if "category_id" in sent:
            await self._check_category(req.category_id, user_id=user_id, scope=debt.scope, family_id=debt.family_id)
            debt.category_id = req.category_id
        if req.add_emi_to_paid is not None:
            debt.add_emi_to_paid = req.add_emi_to_paid
        if req.document_id is not None:
            debt.document_id = req.document_id
        if (
            req.let_everyone_edit is not None
            and debt.scope == "FAMILY"
            and req.let_everyone_edit != debt.let_everyone_edit
        ):
            if user_id != debt.created_by and not is_head:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the creator or a family head can change who may edit",
                )
            debt.let_everyone_edit = req.let_everyone_edit
            rule = await self._linked_rule(debt)
            if rule is not None:
                rule.let_everyone_edit = req.let_everyone_edit

        new_status = (req.status or "").upper() or None
        if new_status is not None and new_status not in {"OPEN", "SETTLED"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Status must be OPEN or SETTLED")
        if debt.amount_paid >= debt.amount:
            debt.amount_paid = debt.amount
            new_status = "SETTLED"
        debt.status = new_status or ("OPEN" if debt.amount_paid < debt.amount else "SETTLED")

        rule = await self._linked_rule(debt)
        if rule is not None and debt.status == "SETTLED" and rule.status in {"ACTIVE", "PAUSED"}:
            rule.status = "COMPLETED"

        await self.pg_session.commit()
        await self.pg_session.refresh(debt)
        return debt

    async def delete_debt(self, user_id: UUID, debt_id: UUID) -> None:
        """Stops the EMI schedule; EMI entries already posted stay in history."""
        debt, _ = await self._get_editable(user_id, debt_id)
        rule = await self._linked_rule(debt)
        if rule is not None:
            rule.status = "CANCELLED"
            rule.debt_id = None
        await self.pg_session.delete(debt)
        await self.pg_session.commit()

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.api.routes.debt.simple_debt_models import FosDebt
from app.api.routes.debt.simple_debt_schemas import DebtCreateRequest, DebtUpdateRequest
from app.api.routes.money.model import FosMoneyRule, FosMoneyRuleParty
from app.api.routes.user.model import UserFamilyLink

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

    async def create_debt(self, user_id: UUID, req: DebtCreateRequest) -> FosDebt:
        if req.scope == "FAMILY":
            if not req.family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required for FAMILY scope")
            is_member, _ = await self._check_family_membership(user_id, req.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        else:
            req.family_id = None
            req.owner_type = "SELF"
            req.owner_user_id = user_id

        amt = Decimal(str(req.amount))
        paid = Decimal(str(req.amount_paid)) if req.amount_paid else Decimal("0.00")
        if paid > amt:
            paid = amt # clamp at amount

        debt_status = "SETTLED" if paid >= amt else "OPEN"

        debt = FosDebt(
            scope=req.scope,
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
            let_everyone_edit=req.let_everyone_edit if req.scope == "FAMILY" else False,
            created_by=user_id,
            status=debt_status,
        )
        self.pg_session.add(debt)
        await self.pg_session.flush()

        # If has_emi is enabled, automatically map to a recurring expense rule
        if req.has_emi and req.emi_amount and req.emi_amount > 0 and debt_status == "OPEN":
            emi_rule = FosMoneyRule(
                scope=req.scope,
                family_id=req.family_id,
                owner_user_id=user_id if req.scope == "PERSONAL" else None,
                kind="EXPENSE",
                name=f"{debt.name} EMI",
                amount=Decimal(str(req.emi_amount)),
                frequency=req.frequency.upper() if req.frequency else "MONTHLY",
                next_run_at=req.next_emi_date or datetime.now(timezone.utc),
                let_everyone_edit=debt.let_everyone_edit,
                created_by=user_id,
                debt_id=debt.id,
                status="ACTIVE",
            )
            self.pg_session.add(emi_rule)
            await self.pg_session.flush()

            party = FosMoneyRuleParty(
                rule_id=emi_rule.id,
                party_type="MEMBER" if (req.owner_type == "MEMBER" and req.owner_user_id) else req.owner_type,
                user_id=req.owner_user_id if req.owner_type in ("MEMBER", "SELF") else None,
            )
            self.pg_session.add(party)

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
    ) -> Tuple[List[FosDebt], int]:
        stmt = select(FosDebt).where(FosDebt.scope == scope)
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required")
            is_member, _ = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            stmt = stmt.where(FosDebt.family_id == family_id)
        else:
            stmt = stmt.where(FosDebt.created_by == user_id)

        if status_filter:
            stmt = stmt.where(FosDebt.status == status_filter.upper())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.pg_session.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(FosDebt.created_at.desc())
        items = (await self.pg_session.execute(stmt)).scalars().all()
        return items, total

    async def update_debt(self, user_id: UUID, debt_id: UUID, req: DebtUpdateRequest) -> FosDebt:
        debt = (await self.pg_session.execute(select(FosDebt).where(FosDebt.id == debt_id))).scalars().first()
        if not debt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")

        if debt.scope == "FAMILY":
            is_member, is_head = await self._check_family_membership(user_id, debt.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            if not debt.let_everyone_edit and debt.created_by != user_id and not is_head:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        else:
            if debt.created_by != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        if req.name is not None:
            debt.name = req.name.strip()
        if req.amount is not None:
            debt.amount = Decimal(str(req.amount))
        if req.amount_paid is not None:
            debt.amount_paid = Decimal(str(req.amount_paid))
            if debt.amount_paid >= debt.amount:
                debt.amount_paid = debt.amount
                debt.status = "SETTLED"
                # Stop linked rule
                if debt.linked_rule_id:
                    rule = (await self.pg_session.execute(select(FosMoneyRule).where(FosMoneyRule.id == debt.linked_rule_id))).scalars().first()
                    if rule:
                        rule.status = "CANCELLED"
            else:
                debt.status = "OPEN"
        if req.add_emi_to_paid is not None:
            debt.add_emi_to_paid = req.add_emi_to_paid
        if req.document_id is not None:
            debt.document_id = req.document_id
        if req.let_everyone_edit is not None:
            debt.let_everyone_edit = req.let_everyone_edit
        if req.status is not None:
            debt.status = req.status.upper()

        await self.pg_session.commit()
        await self.pg_session.refresh(debt)
        return debt

    async def delete_debt(self, user_id: UUID, debt_id: UUID) -> None:
        debt = (await self.pg_session.execute(select(FosDebt).where(FosDebt.id == debt_id))).scalars().first()
        if not debt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")

        if debt.scope == "FAMILY":
            is_member, is_head = await self._check_family_membership(user_id, debt.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            if not debt.let_everyone_edit and debt.created_by != user_id and not is_head:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        else:
            if debt.created_by != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        if debt.linked_rule_id:
            rule = (await self.pg_session.execute(select(FosMoneyRule).where(FosMoneyRule.id == debt.linked_rule_id))).scalars().first()
            if rule:
                await self.pg_session.delete(rule)

        await self.pg_session.delete(debt)
        await self.pg_session.commit()

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.api.routes.money.model import (
    FosMoneyRule,
    FosMoneyRuleParty,
    FosMoneyEvent,
    FosMoneyEventParty,
)
from app.api.routes.money.money_schemas import (
    MoneyRuleCreateRequest,
    MoneyRuleUpdateRequest,
    MoneyEventCreateRequest,
)
from app.api.routes.family.model import (
    Family,
    FamilyTotalSavings,
    UserGlobalPersonalSavings,
    SavingsLedger,
)
from app.api.routes.user.model import UserFamilyLink
from app.core.constants import (
    POOL_FAMILY,
    POOL_PERSONAL,
    LEDGER_IN,
    LEDGER_OUT,
)

logger = logging.getLogger(__name__)


class MoneyService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def _check_family_membership(self, user_id: UUID, family_id: UUID) -> Tuple[bool, bool]:
        """Return (is_member, is_head)."""
        stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        link = (await self.pg_session.execute(stmt)).scalars().first()
        if not link:
            return False, False
        return True, link.is_family_manager

    # --- Rules (Recurring) ---

    async def create_rule(self, user_id: UUID, req: MoneyRuleCreateRequest) -> FosMoneyRule:
        if req.scope == "FAMILY":
            if not req.family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id is required for FAMILY scope.")
            is_member, _ = await self._check_family_membership(user_id, req.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this family.")
        else:
            req.family_id = None

        from app.api.routes.family.model import Family
        from app.api.routes.profile.model import FosProfile
        from app.core.tz_eighteen import at_eighteen_utc

        tz = "Asia/Kolkata"
        if req.scope == "FAMILY" and req.family_id:
            fam = await self.pg_session.get(Family, req.family_id)
            if fam is not None and getattr(fam, "timezone", None):
                tz = fam.timezone
        else:
            profile = await self.pg_session.get(FosProfile, user_id)
            if profile is not None:
                tz = profile.timezone

        rule = FosMoneyRule(
            scope=req.scope,
            family_id=req.family_id,
            owner_user_id=user_id if req.scope == "PERSONAL" else None,
            kind=req.kind.upper(),
            name=req.name.strip(),
            amount=Decimal(str(req.amount)),
            category_id=req.category_id,
            frequency=req.frequency.upper(),
            next_run_at=at_eighteen_utc(req.next_run_at, tz),
            document_id=req.document_id,
            let_everyone_edit=req.let_everyone_edit,
            created_by=user_id,
            status="ACTIVE",
        )
        self.pg_session.add(rule)
        await self.pg_session.flush()

        # Add parties
        if req.parties:
            for p in req.parties:
                party = FosMoneyRuleParty(
                    rule_id=rule.id,
                    party_type=p.party_type.upper(),
                    user_id=p.user_id,
                )
                self.pg_session.add(party)
        else:
            default_party = FosMoneyRuleParty(
                rule_id=rule.id,
                party_type="FAMILY" if req.scope == "FAMILY" else "MEMBER",
                user_id=user_id if req.scope == "PERSONAL" else None,
            )
            self.pg_session.add(default_party)

        await self.pg_session.commit()
        await self.pg_session.refresh(rule)
        return rule

    async def list_rules(
        self,
        user_id: UUID,
        scope: str,
        family_id: Optional[UUID] = None,
        kind: Optional[str] = None,
    ) -> List[FosMoneyRule]:
        stmt = select(FosMoneyRule).where(
            FosMoneyRule.scope == scope,
            FosMoneyRule.status == "ACTIVE",
        )
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required for family scope")
            is_member, _ = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            stmt = stmt.where(FosMoneyRule.family_id == family_id)
        else:
            stmt = stmt.where(FosMoneyRule.created_by == user_id)

        if kind:
            stmt = stmt.where(FosMoneyRule.kind == kind.upper())

        stmt = stmt.order_by(FosMoneyRule.next_run_at.asc())
        res = await self.pg_session.execute(stmt)
        return res.scalars().all()

    async def update_rule(self, user_id: UUID, rule_id: UUID, req: MoneyRuleUpdateRequest) -> FosMoneyRule:
        rule = (await self.pg_session.execute(select(FosMoneyRule).where(FosMoneyRule.id == rule_id))).scalars().first()
        if not rule:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

        # Edit check
        if rule.scope == "FAMILY":
            is_member, is_head = await self._check_family_membership(user_id, rule.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            if not rule.let_everyone_edit and rule.created_by != user_id and not is_head:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only creator or head can edit this rule.")
        else:
            if rule.created_by != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        if req.name is not None:
            rule.name = req.name.strip()
        if req.amount is not None:
            rule.amount = Decimal(str(req.amount))
        if req.category_id is not None:
            rule.category_id = req.category_id
        if req.frequency is not None:
            rule.frequency = req.frequency.upper()
        if req.next_run_at is not None:
            rule.next_run_at = req.next_run_at
        if req.document_id is not None:
            rule.document_id = req.document_id
        if req.let_everyone_edit is not None:
            rule.let_everyone_edit = req.let_everyone_edit

        await self.pg_session.commit()
        await self.pg_session.refresh(rule)
        return rule

    async def delete_rule(self, user_id: UUID, rule_id: UUID) -> None:
        rule = (await self.pg_session.execute(select(FosMoneyRule).where(FosMoneyRule.id == rule_id))).scalars().first()
        if not rule:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

        if rule.scope == "FAMILY":
            is_member, is_head = await self._check_family_membership(user_id, rule.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            if not rule.let_everyone_edit and rule.created_by != user_id and not is_head:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        else:
            if rule.created_by != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        rule.status = "CANCELLED"
        await self.pg_session.commit()

    # --- Events (One-time and hits) ---

    async def create_event(self, user_id: UUID, req: MoneyEventCreateRequest) -> FosMoneyEvent:
        amt = Decimal(str(req.amount))
        now = req.occurred_at or datetime.now(timezone.utc)
        kind = req.kind.upper()
        direction = LEDGER_IN if kind == "INCOME" else LEDGER_OUT
        source_type = f"{kind}_ONE_TIME"

        if req.scope == "FAMILY":
            if not req.family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required for family scope")
            is_member, _ = await self._check_family_membership(user_id, req.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

            # Update family total savings
            savings = (await self.pg_session.execute(
                select(FamilyTotalSavings).where(FamilyTotalSavings.family_id == req.family_id)
            )).scalars().first()
            if not savings:
                savings = FamilyTotalSavings(family_id=req.family_id, origin_amount=Decimal("0.0"), total_savings=Decimal("0.0"))
                self.pg_session.add(savings)

            if direction == LEDGER_IN:
                savings.total_savings += amt
            else:
                savings.total_savings -= amt

            ledger = SavingsLedger(
                pool_type=POOL_FAMILY,
                family_id=req.family_id,
                user_id=user_id,
                amount=amt,
                direction=direction,
                source_type=source_type,
                description=req.name,
                document_id=req.document_id,
                occurred_at=now,
            )
            self.pg_session.add(ledger)
        else:
            # Personal pool update
            savings = (await self.pg_session.execute(
                select(UserGlobalPersonalSavings).where(UserGlobalPersonalSavings.user_id == user_id)
            )).scalars().first()
            if not savings:
                savings = UserGlobalPersonalSavings(user_id=user_id, origin_amount=Decimal("0.0"), total_savings=Decimal("0.0"))
                self.pg_session.add(savings)

            if direction == LEDGER_IN:
                savings.total_savings += amt
            else:
                savings.total_savings -= amt

            ledger = SavingsLedger(
                pool_type=POOL_PERSONAL,
                family_id=None,
                user_id=user_id,
                amount=amt,
                direction=direction,
                source_type=source_type,
                description=req.name,
                document_id=req.document_id,
                occurred_at=now,
            )
            self.pg_session.add(ledger)

        event = FosMoneyEvent(
            scope=req.scope,
            family_id=req.family_id if req.scope == "FAMILY" else None,
            owner_user_id=user_id if req.scope == "PERSONAL" else None,
            kind=kind,
            name=req.name.strip(),
            amount=amt,
            category_id=req.category_id,
            document_id=req.document_id,
            let_everyone_edit=req.let_everyone_edit,
            occurred_at=now,
            created_by=user_id,
        )
        self.pg_session.add(event)
        await self.pg_session.flush()

        # Add parties
        if req.parties:
            for p in req.parties:
                party = FosMoneyEventParty(
                    event_id=event.id,
                    party_type=p.party_type.upper(),
                    user_id=p.user_id,
                )
                self.pg_session.add(party)
        else:
            party = FosMoneyEventParty(
                event_id=event.id,
                party_type="FAMILY" if req.scope == "FAMILY" else "MEMBER",
                user_id=user_id if req.scope == "PERSONAL" else None,
            )
            self.pg_session.add(party)

        await self.pg_session.commit()
        await self.pg_session.refresh(event)
        return event

    async def list_events(
        self,
        user_id: UUID,
        scope: str,
        family_id: Optional[UUID] = None,
        kind: Optional[str] = None,
        source: Optional[str] = None,
        category_id: Optional[UUID] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Tuple[List[FosMoneyEvent], int]:
        stmt = select(FosMoneyEvent).where(FosMoneyEvent.scope == scope)
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required")
            is_member, _ = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            stmt = stmt.where(FosMoneyEvent.family_id == family_id)
        else:
            stmt = stmt.where(FosMoneyEvent.created_by == user_id)

        if kind:
            stmt = stmt.where(FosMoneyEvent.kind == kind.upper())

        source_norm = (source or "").strip().upper()
        if source_norm in ("ONE_TIME", "ONETIME", "EVENT"):
            stmt = stmt.where(FosMoneyEvent.rule_id.is_(None))
        elif source_norm in ("RECURRING", "RULE"):
            stmt = stmt.where(FosMoneyEvent.rule_id.is_not(None))

        if category_id:
            stmt = stmt.where(FosMoneyEvent.category_id == category_id)

        if from_date:
            stmt = stmt.where(FosMoneyEvent.occurred_at >= from_date)
        if to_date:
            stmt = stmt.where(FosMoneyEvent.occurred_at <= to_date)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.pg_session.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(FosMoneyEvent.occurred_at.desc()).offset(offset).limit(limit)
        items = (await self.pg_session.execute(stmt)).scalars().all()
        return items, total

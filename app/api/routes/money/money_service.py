import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.api.routes.category.category_service import CategoryService
from app.api.routes.family.model import Family
from app.api.routes.insurance.model import FosInsuranceInstallment
from app.api.routes.money.model import (
    FosMoneyEvent,
    FosMoneyEventParty,
    FosMoneyRule,
    FosMoneyRuleParty,
)
from app.api.routes.money.money_schemas import (
    MoneyEventCreateRequest,
    MoneyEventUpdateRequest,
    MoneyRuleCreateRequest,
    MoneyRuleUpdateRequest,
    PartyInput,
)
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.pagination import PaginationParams
from app.core.constants import LEDGER_IN, LEDGER_OUT, LEDGER_SOURCE_ADJUSTMENT
from app.core.money_alerts import queue_overdraft_alerts, send_overdraft_emails
from app.core.date_advance import normalize_frequency
from app.core.savings_ledger_service import SavingsLedgerService
from app.core.scope import can_edit_shared
from app.core.tz_eighteen import at_eighteen_utc, local_date
from app.scheduler.money_rule_cron import next_due, pool_for

logger = logging.getLogger(__name__)

KINDS = {"INCOME", "EXPENSE"}
RULE_VISIBLE_STATUSES = ("ACTIVE", "PAUSED")


def _bad(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": message, "errors": {field: message}},
    )


class MoneyService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def _membership(self, user_id: UUID, family_id: UUID | None) -> Tuple[bool, bool]:
        """Return (is_member, is_head)."""
        if family_id is None:
            return False, False
        stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        link = (await self.pg_session.execute(stmt)).scalars().first()
        if not link:
            return False, False
        return True, link.is_family_manager

    async def _require_member(self, user_id: UUID, family_id: UUID | None) -> bool:
        if family_id is None:
            raise _bad("familyId", "family_id is required for family scope")
        is_member, is_head = await self._membership(user_id, family_id)
        if not is_member:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this family")
        return is_head

    async def _scope_tz(self, scope: str, family_id: UUID | None, user_id: UUID) -> str:
        if scope == "FAMILY" and family_id:
            fam = await self.pg_session.get(Family, family_id)
            if fam is not None and fam.timezone:
                return fam.timezone
        profile = await self.pg_session.get(FosProfile, user_id)
        return profile.timezone if profile is not None else "Asia/Kolkata"

    @staticmethod
    def _scope(raw: str) -> str:
        scope = (raw or "FAMILY").upper()
        if scope not in {"FAMILY", "PERSONAL"}:
            raise _bad("scope", "Scope must be FAMILY or PERSONAL")
        return scope

    @staticmethod
    def _kind(raw: str) -> str:
        kind = (raw or "").upper()
        if kind not in KINDS:
            raise _bad("kind", "Kind must be INCOME or EXPENSE")
        return kind

    @staticmethod
    def _frequency(raw: str) -> str:
        try:
            return normalize_frequency(raw)
        except ValueError as exc:
            raise _bad("frequency", str(exc)) from exc

    async def _check_category(
        self, category_id: UUID | None, *, user_id: UUID, scope: str, family_id: UUID | None, kind: str
    ) -> None:
        await CategoryService(self.pg_session).require_usable(
            category_id, user_id=user_id, scope=scope, family_id=family_id, category_type=kind
        )

    def _parties(self, parties: List[PartyInput], *, scope: str, user_id: UUID) -> list[tuple[str, UUID | None]]:
        if parties:
            return [(p.party_type.upper(), p.user_id) for p in parties]
        return [("FAMILY", None)] if scope == "FAMILY" else [("MEMBER", user_id)]

    async def can_edit_rule(self, user_id: UUID, rule: FosMoneyRule) -> bool:
        if rule.scope == "PERSONAL":
            return rule.owner_user_id == user_id or rule.created_by == user_id
        is_member, is_head = await self._membership(user_id, rule.family_id)
        return is_member and can_edit_shared(
            actor_id=user_id,
            creator_id=rule.created_by,
            is_head=is_head,
            let_everyone_edit=rule.let_everyone_edit,
        )

    # --- Rules (recurring) ---

    async def create_rule(self, user_id: UUID, req: MoneyRuleCreateRequest) -> FosMoneyRule:
        scope = self._scope(req.scope)
        kind = self._kind(req.kind)
        family_id = req.family_id if scope == "FAMILY" else None
        if scope == "FAMILY":
            await self._require_member(user_id, family_id)
        await self._check_category(req.category_id, user_id=user_id, scope=scope, family_id=family_id, kind=kind)

        tz = await self._scope_tz(scope, family_id, user_id)
        first = at_eighteen_utc(req.next_run_at, tz)
        end_at = at_eighteen_utc(req.end_at, tz) if req.end_at else None
        if end_at is not None and end_at < first:
            raise _bad("endAt", "End date must be on or after the first date")

        rule = FosMoneyRule(
            scope=scope,
            family_id=family_id,
            owner_user_id=user_id if scope == "PERSONAL" else None,
            kind=kind,
            name=req.name.strip(),
            amount=Decimal(str(req.amount)).quantize(Decimal("0.01")),
            category_id=req.category_id,
            frequency=self._frequency(req.frequency),
            every_n=req.every_n,
            anchor_day=local_date(first, tz).day,
            next_run_at=first,
            end_at=end_at,
            max_runs=req.max_runs,
            document_id=req.document_id,
            let_everyone_edit=req.let_everyone_edit if scope == "FAMILY" else False,
            created_by=user_id,
            status="ACTIVE",
        )
        self.pg_session.add(rule)
        await self.pg_session.flush()
        for party_type, party_user in self._parties(req.parties, scope=scope, user_id=user_id):
            self.pg_session.add(FosMoneyRuleParty(rule_id=rule.id, party_type=party_type, user_id=party_user))
        await self.pg_session.commit()
        await self.pg_session.refresh(rule)
        return rule

    async def list_rules(
        self,
        user_id: UUID,
        scope: str,
        family_id: Optional[UUID] = None,
        kind: Optional[str] = None,
        *,
        pagination: PaginationParams,
        q: str | None = None,
    ) -> Tuple[List[FosMoneyRule], int]:
        scope = self._scope(scope)
        filters = [FosMoneyRule.scope == scope, FosMoneyRule.status.in_(RULE_VISIBLE_STATUSES)]
        if scope == "FAMILY":
            await self._require_member(user_id, family_id)
            filters.append(FosMoneyRule.family_id == family_id)
        else:
            filters.append(FosMoneyRule.owner_user_id == user_id)
        if kind:
            filters.append(FosMoneyRule.kind == self._kind(kind))
        if q and q.strip():
            filters.append(func.lower(FosMoneyRule.name).contains(q.strip().lower(), autoescape=True))

        total = (
            await self.pg_session.execute(select(func.count()).select_from(FosMoneyRule).where(*filters))
        ).scalar_one()
        rows = (
            await self.pg_session.execute(
                select(FosMoneyRule)
                .where(*filters)
                .order_by(FosMoneyRule.next_run_at.asc(), FosMoneyRule.id)
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def _get_rule_for_edit(self, user_id: UUID, rule_id: UUID) -> FosMoneyRule:
        rule = await self.pg_session.get(FosMoneyRule, rule_id, with_for_update=True)
        if rule is None or rule.status in {"CANCELLED"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring item not found")
        if rule.scope == "FAMILY":
            await self._require_member(user_id, rule.family_id)
        if not await self.can_edit_rule(user_id, rule):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the creator or a family head can change this item",
            )
        return rule

    async def update_rule(self, user_id: UUID, rule_id: UUID, req: MoneyRuleUpdateRequest) -> FosMoneyRule:
        rule = await self._get_rule_for_edit(user_id, rule_id)
        sent = req.model_fields_set
        tz = await self._scope_tz(rule.scope, rule.family_id, rule.created_by)

        if req.name is not None:
            rule.name = req.name.strip()
        if req.amount is not None:
            rule.amount = Decimal(str(req.amount)).quantize(Decimal("0.01"))
        if "category_id" in sent:
            await self._check_category(
                req.category_id, user_id=user_id, scope=rule.scope, family_id=rule.family_id, kind=rule.kind
            )
            rule.category_id = req.category_id
        if req.frequency is not None:
            rule.frequency = self._frequency(req.frequency)
        if req.every_n is not None:
            rule.every_n = req.every_n
        if req.next_run_at is not None:
            rule.next_run_at = at_eighteen_utc(req.next_run_at, tz)
            rule.anchor_day = local_date(rule.next_run_at, tz).day
        if "end_at" in sent:
            rule.end_at = at_eighteen_utc(req.end_at, tz) if req.end_at else None
        if "max_runs" in sent:
            rule.max_runs = req.max_runs
        if req.document_id is not None:
            rule.document_id = req.document_id
        if (
            req.let_everyone_edit is not None
            and rule.scope == "FAMILY"
            and req.let_everyone_edit != rule.let_everyone_edit
        ):
            _, is_head = await self._membership(user_id, rule.family_id)
            if rule.created_by != user_id and not is_head:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the creator or a family head can change who may edit",
                )
            rule.let_everyone_edit = req.let_everyone_edit
        if req.parties is not None:
            rule.parties.clear()
            await self.pg_session.flush()
            for party_type, party_user in self._parties(req.parties, scope=rule.scope, user_id=user_id):
                rule.parties.append(FosMoneyRuleParty(rule_id=rule.id, party_type=party_type, user_id=party_user))

        if req.status is not None:
            new_status = req.status.upper()
            if new_status not in {"ACTIVE", "PAUSED"}:
                raise _bad("status", "Status must be ACTIVE or PAUSED")
            if new_status == "ACTIVE" and rule.status == "PAUSED":
                # Resuming skips the paused periods instead of back-posting them.
                now = datetime.now(timezone.utc)
                while rule.next_run_at <= now:
                    rule.next_run_at = next_due(rule, rule.next_run_at, tz)
            if rule.status in {"ACTIVE", "PAUSED"}:
                rule.status = new_status

        if rule.end_at is not None and rule.end_at < rule.next_run_at:
            raise _bad("endAt", "End date must be on or after the next date")

        await self.pg_session.commit()
        await self.pg_session.refresh(rule)
        return rule

    async def delete_rule(self, user_id: UUID, rule_id: UUID) -> None:
        """Stops future runs; posted history stays."""
        rule = await self._get_rule_for_edit(user_id, rule_id)
        rule.status = "CANCELLED"
        await self.pg_session.commit()

    # --- Events (one-time entries and recurring runs) ---

    async def create_event(self, user_id: UUID, req: MoneyEventCreateRequest) -> FosMoneyEvent:
        scope = self._scope(req.scope)
        kind = self._kind(req.kind)
        family_id = req.family_id if scope == "FAMILY" else None
        if scope == "FAMILY":
            await self._require_member(user_id, family_id)
        await self._check_category(req.category_id, user_id=user_id, scope=scope, family_id=family_id, kind=kind)

        amount = Decimal(str(req.amount)).quantize(Decimal("0.01"))
        when = req.occurred_at or datetime.now(timezone.utc)
        owner = user_id if scope == "PERSONAL" else None
        event = FosMoneyEvent(
            scope=scope,
            family_id=family_id,
            owner_user_id=owner,
            kind=kind,
            name=req.name.strip(),
            amount=amount,
            category_id=req.category_id,
            document_id=req.document_id,
            let_everyone_edit=req.let_everyone_edit,
            occurred_at=when,
            created_by=user_id,
        )
        self.pg_session.add(event)
        await self.pg_session.flush()
        for party_type, party_user in self._parties(req.parties, scope=scope, user_id=user_id):
            self.pg_session.add(FosMoneyEventParty(event_id=event.id, party_type=party_type, user_id=party_user))

        ledger = SavingsLedgerService(self.pg_session)
        pool = pool_for(scope, family_id, owner)
        await ledger.apply_movement(
            pool,
            amount,
            LEDGER_IN if kind == "INCOME" else LEDGER_OUT,
            f"{kind}_ONE_TIME",
            source_id=event.id,
            description=event.name,
            document_id=req.document_id,
            occurred_at=when,
        )
        alerts = []
        if kind == "EXPENSE":
            balance_after = await ledger.balance(pool)
            event.is_overdrawn = balance_after < 0
            if event.is_overdrawn:
                alerts = await queue_overdraft_alerts(
                    self.pg_session,
                    family_id=family_id,
                    owner_user_id=owner,
                    rule_name=event.name,
                    amount=amount,
                    balance_after=balance_after,
                    event_id=event.id,
                )

        await self.pg_session.commit()
        await self.pg_session.refresh(event)
        await send_overdraft_emails(alerts)
        return event

    async def can_edit_event(self, user_id: UUID, event: FosMoneyEvent) -> bool:
        if event.scope == "PERSONAL":
            return event.owner_user_id == user_id
        is_member, is_head = await self._membership(user_id, event.family_id)
        return is_member and can_edit_shared(
            actor_id=user_id,
            creator_id=event.created_by,
            is_head=is_head,
            let_everyone_edit=event.let_everyone_edit,
        )

    async def _get_event_for_edit(self, user_id: UUID, event_id: UUID) -> FosMoneyEvent:
        event = await self.pg_session.get(FosMoneyEvent, event_id, with_for_update=True)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
        if event.scope == "FAMILY":
            await self._require_member(user_id, event.family_id)
        if not await self.can_edit_event(user_id, event):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the creator or a family head can change this entry",
            )
        await self._reject_linked_payment(event)
        return event

    async def _reject_linked_payment(self, event: FosMoneyEvent) -> None:
        """EMI and premium payments also update their debt / installment, so they
        are changed from those pages instead."""
        if event.rule_id is not None:
            rule = await self.pg_session.get(FosMoneyRule, event.rule_id)
            if rule is not None and rule.debt_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This is a debt EMI payment; change it from the Debts page",
                )
        paid_installment = await self.pg_session.execute(
            select(FosInsuranceInstallment.id).where(FosInsuranceInstallment.paid_event_id == event.id).limit(1)
        )
        if paid_installment.first() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This is an insurance premium payment; change it from the Insurance page",
            )

    async def _adjust_balance(self, event: FosMoneyEvent, delta: Decimal, note: str) -> None:
        """delta is the change in the entry's own amount (+ means a larger entry)."""
        if delta == 0:
            return
        is_income = event.kind == "INCOME"
        grows_pool = (delta > 0) == is_income
        await SavingsLedgerService(self.pg_session).apply_movement(
            pool_for(event.scope, event.family_id, event.owner_user_id),
            abs(delta),
            LEDGER_IN if grows_pool else LEDGER_OUT,
            LEDGER_SOURCE_ADJUSTMENT,
            source_id=event.id,
            description=f"{note}: {event.name}",
        )

    async def update_event(self, user_id: UUID, event_id: UUID, req: MoneyEventUpdateRequest) -> FosMoneyEvent:
        event = await self._get_event_for_edit(user_id, event_id)
        sent = req.model_fields_set
        if req.name is not None:
            event.name = req.name.strip()
        if "category_id" in sent:
            await self._check_category(
                req.category_id, user_id=user_id, scope=event.scope, family_id=event.family_id, kind=event.kind
            )
            event.category_id = req.category_id
        if req.document_id is not None:
            event.document_id = req.document_id
        if req.occurred_at is not None:
            event.occurred_at = req.occurred_at
        if (
            req.let_everyone_edit is not None
            and event.scope == "FAMILY"
            and req.let_everyone_edit != event.let_everyone_edit
        ):
            _, is_head = await self._membership(user_id, event.family_id)
            if event.created_by != user_id and not is_head:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the creator or a family head can change who may edit",
                )
            event.let_everyone_edit = req.let_everyone_edit
        if req.amount is not None:
            new_amount = Decimal(str(req.amount)).quantize(Decimal("0.01"))
            await self._adjust_balance(event, new_amount - Decimal(str(event.amount)), "Edited")
            event.amount = new_amount
            if event.kind == "EXPENSE":
                pool = pool_for(event.scope, event.family_id, event.owner_user_id)
                event.is_overdrawn = (await SavingsLedgerService(self.pg_session).balance(pool)) < 0
        await self.pg_session.commit()
        await self.pg_session.refresh(event)
        return event

    async def delete_event(self, user_id: UUID, event_id: UUID) -> None:
        """Removes the entry and reverses its effect on the balance."""
        event = await self._get_event_for_edit(user_id, event_id)
        await self._adjust_balance(event, -Decimal(str(event.amount)), "Deleted")
        await self.pg_session.delete(event)
        await self.pg_session.commit()

    async def list_events(
        self,
        user_id: UUID,
        scope: str,
        family_id: Optional[UUID] = None,
        kind: Optional[str] = None,
        source: Optional[str] = None,
        category_id: Optional[UUID] = None,
        rule_id: Optional[UUID] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        q: Optional[str] = None,
        *,
        pagination: PaginationParams,
    ) -> Tuple[List[FosMoneyEvent], int]:
        scope = self._scope(scope)
        filters = [FosMoneyEvent.scope == scope]
        if scope == "FAMILY":
            await self._require_member(user_id, family_id)
            filters.append(FosMoneyEvent.family_id == family_id)
        else:
            filters.append(FosMoneyEvent.owner_user_id == user_id)
        if kind:
            filters.append(FosMoneyEvent.kind == self._kind(kind))

        source_norm = (source or "").strip().upper()
        if source_norm in ("ONE_TIME", "ONETIME", "EVENT"):
            filters.append(FosMoneyEvent.rule_id.is_(None))
        elif source_norm in ("RECURRING", "RULE"):
            filters.append(FosMoneyEvent.rule_id.is_not(None))
        if rule_id:
            filters.append(FosMoneyEvent.rule_id == rule_id)
        if category_id:
            filters.append(FosMoneyEvent.category_id == category_id)
        if from_date:
            filters.append(FosMoneyEvent.occurred_at >= from_date)
        if to_date:
            filters.append(FosMoneyEvent.occurred_at <= to_date)
        if q and q.strip():
            filters.append(func.lower(FosMoneyEvent.name).contains(q.strip().lower(), autoescape=True))

        total = (
            await self.pg_session.execute(select(func.count()).select_from(FosMoneyEvent).where(*filters))
        ).scalar_one()
        rows = (
            await self.pg_session.execute(
                select(FosMoneyEvent)
                .where(*filters)
                .order_by(FosMoneyEvent.occurred_at.desc(), FosMoneyEvent.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return list(rows), total

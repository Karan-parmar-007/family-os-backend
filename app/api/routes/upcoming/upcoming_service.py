"""Upcoming: projected recurring income/expense runs, insurance installments and transfers.

Projections use the same calendar stepping as the scheduler, so what shows
here is what will post.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family.model import Family
from app.api.routes.insurance.model import FamilyInsurance, FosInsuranceInstallment, PersonalInsurance
from app.api.routes.money.model import FosMoneyRule
from app.api.routes.profile.model import FosProfile
from app.api.routes.transfer.model import Transfer
from app.api.routes.upcoming.upcoming_schemas import UpcomingItem
from app.core.constants import TRANSFER_STATUS_ACTIVE, TRANSFER_STATUS_PENDING
from app.core.tz_eighteen import local_date, step_eighteen_utc

_MAX_OCCURRENCES = 120


def _project_rule(rule: FosMoneyRule, horizon_end: datetime, tz: str) -> list[datetime]:
    out: list[datetime] = []
    cursor = rule.next_run_at
    runs = rule.run_count or 0
    anchor = rule.anchor_day or local_date(cursor, tz).day
    while cursor <= horizon_end and len(out) < _MAX_OCCURRENCES:
        if rule.end_at is not None and cursor > rule.end_at:
            break
        if rule.max_runs is not None and runs >= rule.max_runs:
            break
        out.append(cursor)
        runs += 1
        cursor = step_eighteen_utc(cursor, tz, rule.frequency, every_n=rule.every_n or 1, anchor_day=anchor)
    return out


def _project_transfer(t: Transfer, horizon_end: datetime, tz: str) -> list[datetime]:
    out: list[datetime] = []
    cursor = t.next_run_date
    anchor = local_date(cursor, tz).day
    while cursor <= horizon_end and len(out) < _MAX_OCCURRENCES:
        if t.end_date is not None and cursor > t.end_date:
            break
        out.append(cursor)
        cursor = step_eighteen_utc(cursor, tz, t.recurring_every or "MONTHLY", anchor_day=anchor)
    return out


class UpcomingService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def _tz(self, family_id: UUID | None, user_id: UUID) -> str:
        if family_id is not None:
            fam = await self.pg_session.get(Family, family_id)
            if fam is not None and fam.timezone:
                return fam.timezone
        profile = await self.pg_session.get(FosProfile, user_id)
        return profile.timezone if profile is not None else "Asia/Kolkata"

    async def project_upcoming(
        self,
        family_id: UUID | None,
        user_id: UUID,
        *,
        horizon_days: int = 90,
        scope: str | None = None,
    ) -> list[UpcomingItem]:
        now = datetime.now(timezone.utc)
        horizon_end = now + timedelta(days=horizon_days)
        personal = (scope or "").lower() == "personal" or family_id is None
        tz = await self._tz(None if personal else family_id, user_id)
        items: list[UpcomingItem] = []

        rule_stmt = select(FosMoneyRule).where(FosMoneyRule.status == "ACTIVE")
        if personal:
            rule_stmt = rule_stmt.where(FosMoneyRule.scope == "PERSONAL", FosMoneyRule.owner_user_id == user_id)
        else:
            rule_stmt = rule_stmt.where(FosMoneyRule.scope == "FAMILY", FosMoneyRule.family_id == family_id)
        for rule in (await self.pg_session.execute(rule_stmt)).scalars().all():
            kind = "DEBT_EMI" if rule.debt_id else "INSURANCE_PREMIUM" if rule.insurance_id else rule.kind
            for dt in _project_rule(rule, horizon_end, tz):
                items.append(
                    UpcomingItem(
                        type=kind,
                        direction="IN" if rule.kind == "INCOME" else "OUT",
                        name=rule.name,
                        amount=rule.amount,
                        source_type="MONEY_RULE",
                        source_id=rule.id,
                        is_personal=rule.scope == "PERSONAL",
                        date=dt,
                    )
                )

        if personal:
            policies = select(PersonalInsurance.id, PersonalInsurance.insurance_name).where(
                PersonalInsurance.user_id == user_id, PersonalInsurance.status == "ACTIVE"
            )
        else:
            policies = select(FamilyInsurance.id, FamilyInsurance.insurance_name).where(
                FamilyInsurance.family_id == family_id, FamilyInsurance.status == "ACTIVE"
            )
        names = dict((await self.pg_session.execute(policies)).all())
        if names:
            inst_stmt = select(FosInsuranceInstallment).where(
                FosInsuranceInstallment.insurance_id.in_(list(names)),
                FosInsuranceInstallment.status == "PENDING",
                FosInsuranceInstallment.due_at <= horizon_end,
            )
            for inst in (await self.pg_session.execute(inst_stmt)).scalars().all():
                items.append(
                    UpcomingItem(
                        type="INSURANCE_PREMIUM",
                        direction="OUT",
                        name=names[inst.insurance_id],
                        amount=inst.amount,
                        source_type="INSURANCE",
                        source_id=inst.insurance_id,
                        is_personal=personal,
                        date=inst.due_at,
                    )
                )

        if personal:
            sent = and_(Transfer.from_scope == "PERSONAL", Transfer.from_user_id == user_id)
            received = and_(Transfer.to_scope == "PERSONAL", Transfer.to_user_id == user_id)
        else:
            sent = and_(Transfer.from_scope == "FAMILY", Transfer.family_id == family_id)
            received = and_(Transfer.to_scope == "FAMILY", Transfer.to_family_id == family_id)
        xfer_stmt = select(Transfer).where(
            or_(sent, received),
            Transfer.status.in_((TRANSFER_STATUS_PENDING, TRANSFER_STATUS_ACTIVE)),
        )
        for t in (await self.pg_session.execute(xfer_stmt)).scalars().all():
            outgoing = (t.from_scope == "PERSONAL" and t.from_user_id == user_id) if personal else (
                t.from_scope == "FAMILY" and t.family_id == family_id
            )
            direction = "OUT" if outgoing else "IN"
            if t.status == TRANSFER_STATUS_PENDING:
                items.append(
                    UpcomingItem(
                        type="TRANSFER_OFFER",
                        direction=direction,
                        name=t.note or "Transfer waiting for acceptance",
                        amount=t.amount,
                        source_type="TRANSFER",
                        source_id=t.id,
                        is_personal=personal,
                        date=t.created_at,
                    )
                )
            elif t.is_recurring and t.next_run_date:
                for dt in _project_transfer(t, horizon_end, tz):
                    items.append(
                        UpcomingItem(
                            type="AUTO_TRANSFER",
                            direction=direction,
                            name=t.note or "Recurring transfer",
                            amount=t.amount,
                            source_type="TRANSFER",
                            source_id=t.id,
                            is_personal=personal,
                            date=dt,
                        )
                    )

        items.sort(key=lambda i: (i.date, i.name))
        return items

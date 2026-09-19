"""Upcoming: money rules + transfer offers. No goals/plans/old debt."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.money.model import FosMoneyRule
from app.api.routes.transfer.model import Transfer
from app.api.routes.upcoming.upcoming_schemas import UpcomingItem
from app.core.constants import TRANSFER_STATUS_ACTIVE, TRANSFER_STATUS_PENDING
from app.core.date_advance import advance_next_date

_MAX_OCCURRENCES = 60


def _project(start: datetime | None, horizon_end: datetime, every: str | None) -> list[datetime]:
    if start is None:
        return []
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    out: list[datetime] = []
    cursor = start
    for _ in range(_MAX_OCCURRENCES):
        if cursor > horizon_end:
            break
        out.append(cursor)
        cursor = advance_next_date(cursor, every=every)
    return out


class UpcomingService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

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
        personal_only = (scope or "").lower() == "personal"
        items: list[UpcomingItem] = []

        rule_stmt = select(FosMoneyRule).where(FosMoneyRule.status == "ACTIVE")
        if personal_only:
            rule_stmt = rule_stmt.where(
                FosMoneyRule.scope == "PERSONAL",
                FosMoneyRule.created_by == user_id,
            )
        else:
            rule_stmt = rule_stmt.where(
                FosMoneyRule.scope == "FAMILY",
                FosMoneyRule.family_id == family_id,
            )
        rules = list((await self.pg_session.execute(rule_stmt)).scalars().all())
        for rule in rules:
            dates = _project(rule.next_run_at, horizon_end, rule.frequency)
            kind = "INCOME" if rule.kind == "INCOME" else "EXPENSE"
            if rule.insurance_id:
                kind = "INSURANCE_PREMIUM"
            elif rule.debt_id:
                kind = "DEBT_EMI"
            direction = "IN" if rule.kind == "INCOME" else "OUT"
            for dt in dates:
                items.append(
                    UpcomingItem(
                        type=kind,
                        direction=direction,
                        name=rule.name,
                        amount=rule.amount,
                        source_type="MONEY_RULE",
                        source_id=rule.id,
                        is_personal=rule.scope == "PERSONAL",
                        date=dt,
                    )
                )

        xfer_stmt = select(Transfer).where(
            or_(
                Transfer.status == TRANSFER_STATUS_PENDING,
                Transfer.status == TRANSFER_STATUS_ACTIVE,
            )
        )
        if personal_only:
            xfer_stmt = xfer_stmt.where(
                or_(
                    Transfer.from_user_id == user_id,
                    Transfer.to_user_id == user_id,
                    Transfer.created_by == user_id,
                )
            )
        else:
            xfer_stmt = xfer_stmt.where(
                or_(Transfer.family_id == family_id, Transfer.to_family_id == family_id)
            )
        transfers = list((await self.pg_session.execute(xfer_stmt)).scalars().all())
        for t in transfers:
            if t.status == TRANSFER_STATUS_PENDING:
                items.append(
                    UpcomingItem(
                        type="TRANSFER_OFFER",
                        direction="OUT",
                        name=t.note or "Transfer offer",
                        amount=t.amount,
                        source_type="TRANSFER",
                        source_id=t.id,
                        is_personal=t.from_scope == "PERSONAL",
                        date=t.created_at,
                    )
                )
            elif t.is_recurring and t.next_run_date:
                for dt in _project(t.next_run_date, horizon_end, t.recurring_every):
                    items.append(
                        UpcomingItem(
                            type="TRANSFER_OFFER",
                            direction="OUT",
                            name=t.note or "Recurring transfer offer",
                            amount=t.amount,
                            source_type="TRANSFER",
                            source_id=t.id,
                            is_personal=t.from_scope == "PERSONAL",
                            date=dt,
                        )
                    )

        items.sort(key=lambda i: i.date)
        return items

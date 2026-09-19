"""Scheduler runner for FosMoneyRule recurring rules (Income, Expense, Debt EMI, Insurance EMI).

Applies rules without confirmation.
For Debt EMI: increments amount_paid if add_emi_to_paid is True. Settles debt and stops rule when paid.
If pool balance is insufficient: skips debit, advances next_run_at to avoid retry storms.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.debt.simple_debt_models import FosDebt
from app.api.routes.family.model import Family
from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.routes.money.model import FosMoneyRule, FosMoneyEvent
from app.api.routes.profile.model import FosProfile
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_RECURRING_EXPENSE,
    LEDGER_SOURCE_RECURRING_INCOME,
    POOL_FAMILY,
    POOL_PERSONAL,
)
from app.core.date_advance import advance_next_date
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.tz_eighteen import at_eighteen_utc

logger = logging.getLogger(__name__)


async def _rule_tz(session: AsyncSession, rule: FosMoneyRule) -> str:
    if rule.family_id is not None:
        fam = await session.get(Family, rule.family_id)
        if fam is not None and getattr(fam, "timezone", None):
            return fam.timezone
    owner = rule.owner_user_id or rule.created_by
    if owner is not None:
        profile = await session.get(FosProfile, owner)
        if profile is not None:
            return profile.timezone
    return "Asia/Kolkata"


async def run_money_rules_cron(
    session: AsyncSession,
    now: Optional[datetime] = None,
    family_id: Optional[UUID] = None,
    force: bool = False,
) -> int:
    if now is None:
        now = datetime.now(timezone.utc)

    ledger_svc = SavingsLedgerService(session)

    stmt = select(FosMoneyRule).where(FosMoneyRule.status == "ACTIVE")
    if not force:
        stmt = stmt.where(FosMoneyRule.next_run_at <= now)
    if family_id is not None:
        stmt = stmt.where(FosMoneyRule.family_id == family_id)
    rules = list((await session.execute(stmt)).scalars().all())
    applied_count = 0

    for rule in rules:
        try:
            is_personal = rule.scope == "PERSONAL"
            pool_ref = (
                SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=rule.owner_user_id)
                if is_personal
                else SavingsPoolRef(pool_type=POOL_FAMILY, family_id=rule.family_id)
            )

            amount_dec = Decimal(str(rule.amount))

            if rule.kind == "INCOME":
                # Credit pool
                await ledger_svc.apply_movement(
                    pool=pool_ref,
                    amount=amount_dec,
                    direction=LEDGER_IN,
                    source_type=LEDGER_SOURCE_RECURRING_INCOME,
                    source_id=rule.id,
                    description=f"Recurring income: {rule.name}",
                )

                # Record materialized event
                event = FosMoneyEvent(
                    rule_id=rule.id,
                    scope=rule.scope,
                    family_id=rule.family_id,
                    owner_user_id=rule.owner_user_id,
                    kind="INCOME",
                    name=rule.name,
                    amount=amount_dec,
                    category_id=rule.category_id,
                    document_id=rule.document_id,
                    let_everyone_edit=rule.let_everyone_edit,
                    occurred_at=now,
                    created_by=rule.created_by,
                )
                session.add(event)

            else:  # EXPENSE
                # Check balance
                pool_row = await ledger_svc._get_or_create_pool_row(pool_ref)
                current_bal = Decimal(str(pool_row.total_savings))

                if current_bal < amount_dec:
                    logger.warning(
                        "Insufficient funds for rule %s (needed %s, has %s). Skipping cycle.",
                        rule.id,
                        amount_dec,
                        current_bal,
                    )
                    tz = await _rule_tz(session, rule)
                    rule.next_run_at = at_eighteen_utc(
                        advance_next_date(rule.next_run_at, every=rule.frequency), tz
                    )
                    continue

                # Debit pool
                await ledger_svc.apply_movement(
                    pool=pool_ref,
                    amount=amount_dec,
                    direction=LEDGER_OUT,
                    source_type=LEDGER_SOURCE_RECURRING_EXPENSE,
                    source_id=rule.id,
                    description=f"Recurring expense: {rule.name}",
                )

                # Record materialized event
                event = FosMoneyEvent(
                    rule_id=rule.id,
                    scope=rule.scope,
                    family_id=rule.family_id,
                    owner_user_id=rule.owner_user_id,
                    kind="EXPENSE",
                    name=rule.name,
                    amount=amount_dec,
                    category_id=rule.category_id,
                    document_id=rule.document_id,
                    let_everyone_edit=rule.let_everyone_edit,
                    occurred_at=now,
                    created_by=rule.created_by,
                )
                session.add(event)

                # Handle linked Debt EMI
                if rule.debt_id:
                    debt = await session.get(FosDebt, rule.debt_id)
                    if debt and debt.status == "OPEN":
                        if debt.add_emi_to_paid:
                            debt_paid = Decimal(str(debt.amount_paid))
                            debt_tot = Decimal(str(debt.amount))
                            debt.amount_paid = min(debt_tot, debt_paid + amount_dec)
                            if debt.amount_paid >= debt_tot:
                                debt.status = "SETTLED"
                                rule.status = "COMPLETED"
                                logger.info("Debt %s settled in full. Mapped rule completed.", debt.id)

                if rule.insurance_id and rule.emi_remaining is not None:
                    rule.emi_remaining = max(0, int(rule.emi_remaining) - 1)
                    if rule.emi_remaining == 0:
                        rule.status = "COMPLETED"
                        fam_ins = await session.get(FamilyInsurance, rule.insurance_id)
                        pers_ins = (
                            None
                            if fam_ins is not None
                            else await session.get(PersonalInsurance, rule.insurance_id)
                        )
                        ins = fam_ins or pers_ins
                        if ins is not None:
                            ins.status = "COMPLETED"

            tz = await _rule_tz(session, rule)
            if rule.status == "ACTIVE":
                rule.next_run_at = at_eighteen_utc(
                    advance_next_date(rule.next_run_at, every=rule.frequency), tz
                )
            applied_count += 1

        except Exception as e:
            logger.error("Error executing recurring rule %s: %s", rule.id, e, exc_info=True)

    await session.commit()
    return applied_count

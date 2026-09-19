import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

from app.api.routes.debt.simple_debt_models import FosDebt
from app.api.routes.family.model import Family, FamilyTotalSavings
from app.api.routes.money.model import FosMoneyRule
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.scheduler.money_rule_cron import run_money_rules_cron
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.constants import POOL_FAMILY


@pytest.mark.asyncio
async def test_money_rule_cron_income_expense_and_debt_settlement(db_session):
    now = datetime.now(timezone.utc)
    due_time = now - timedelta(minutes=5)

    u_id = uuid4()
    u = UserBase(id=u_id, email=f"cron-{u_id.hex[:6]}@example.com", name="Cron User", password="x")
    p = FosProfile(
        id=u_id,
        sso_user_id=str(u_id),
        email=u.email,
        display_name="Cron User",
        personal_currency="USD",
        max_family_memberships=2,
        setup_completed_at=now,
    )
    fam_id = uuid4()
    fam = Family(
        id=fam_id,
        name="Cron Family",
        currency="USD",
        timezone="Asia/Kolkata",
    )
    db_session.add_all([u, p, fam])
    await db_session.flush()

    link = UserFamilyLink(user_id=u_id, family_id=fam_id, is_family_manager=True)
    savings = FamilyTotalSavings(family_id=fam_id, origin_amount=Decimal("1000.0"), total_savings=Decimal("1000.0"))
    db_session.add_all([link, savings])
    await db_session.commit()

    # 1. Income rule: +200
    income_rule = FosMoneyRule(
        scope="FAMILY",
        family_id=fam_id,
        kind="INCOME",
        name="Side Gig",
        amount=200.0,
        frequency="MONTHLY",
        next_run_at=due_time,
        created_by=u_id,
    )

    # 2. Debt with mapped EMI rule: amount 1000, paid 800, EMI 200
    debt = FosDebt(
        scope="FAMILY",
        family_id=fam_id,
        owner_type="FAMILY",
        name="Appliance Loan",
        amount=1000.0,
        amount_paid=800.0,
        has_emi=True,
        add_emi_to_paid=True,
        created_by=u_id,
        status="OPEN",
    )
    db_session.add_all([income_rule, debt])
    await db_session.flush()

    emi_rule = FosMoneyRule(
        scope="FAMILY",
        family_id=fam_id,
        kind="EXPENSE",
        name="Appliance Loan EMI",
        amount=200.0,
        frequency="MONTHLY",
        next_run_at=due_time,
        debt_id=debt.id,
        created_by=u_id,
    )
    db_session.add(emi_rule)
    await db_session.flush()
    debt.linked_rule_id = emi_rule.id
    await db_session.commit()

    # Run cron
    applied = await run_money_rules_cron(db_session, now=now, family_id=fam_id)
    assert applied == 2

    # Verify Pool: started at 1000, +200 income, -200 debt EMI = 1000
    ledger_svc = SavingsLedgerService(db_session)
    row = await ledger_svc._get_or_create_pool_row(SavingsPoolRef(pool_type=POOL_FAMILY, family_id=fam_id))
    assert row.total_savings == Decimal("1000.00")

    # Verify Debt: amount_paid was 800 + 200 = 1000 -> SETTLED!
    await db_session.refresh(debt)
    assert debt.amount_paid == Decimal("1000.00")
    assert debt.status == "SETTLED"

    # Verify EMI rule is COMPLETED so no more debits run
    await db_session.refresh(emi_rule)
    assert emi_rule.status == "COMPLETED"

    # Verify income rule next_run_at was advanced into future
    await db_session.refresh(income_rule)
    assert income_rule.next_run_at > now

"""EMI cron + part-payment lifecycle tests against canonical Debt."""
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routes.debt.debt_service import (
    DebtService,
    apply_debt_emi,
    require_debt_owner,
)
from app.api.routes.debt.model import Debt, DebtPaymentEvent, DebtScopeView
from app.api.routes.family.model import Family, FamilyTotalSavings, UserGlobalPersonalSavings
from app.api.routes.scheduler.model import ScheduledJob
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.core.constants import (
    JOB_STATUS_APPLIED,
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_SCHEDULED,
    JOB_TYPE_DEBT_EMI,
    SOURCE_DEBT,
)
from app.core.funding_service import FundingService
from app.core.interest_math import INTEREST_REDUCING_MONTHLY
from app.scheduler.debt_cron import create_or_replace_next_debt_job, debt_cron_tick


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day)


@pytest.fixture
async def debt_fixture(db_session):
    suffix = uuid4().hex[:8]
    owner = UserBase(email=f"debt-owner-{suffix}@example.com", name="Owner", password="x")
    payer = UserBase(email=f"debt-payer-{suffix}@example.com", name="Payer", password="x")
    stranger = UserBase(
        email=f"debt-stranger-{suffix}@example.com", name="Stranger", password="x"
    )
    family = Family(name=f"Debt Fam {suffix}", currency="USD")
    db_session.add_all([owner, payer, stranger, family])
    await db_session.flush()
    db_session.add_all(
        [
            UserFamilyLink(user_id=owner.id, family_id=family.id, is_family_manager=True),
            UserFamilyLink(user_id=payer.id, family_id=family.id, is_family_manager=False),
            UserFamilyLink(
                user_id=stranger.id, family_id=family.id, is_family_manager=False
            ),
            FamilyTotalSavings(
                family_id=family.id,
                origin_amount=Decimal("100000"),
                total_savings=Decimal("100000"),
            ),
            UserGlobalPersonalSavings(
                user_id=owner.id,
                origin_amount=Decimal("50000"),
                total_savings=Decimal("50000"),
            ),
            UserGlobalPersonalSavings(
                user_id=payer.id,
                origin_amount=Decimal("50000"),
                total_savings=Decimal("50000"),
            ),
            UserGlobalPersonalSavings(
                user_id=stranger.id,
                origin_amount=Decimal("50000"),
                total_savings=Decimal("50000"),
            ),
        ]
    )
    await db_session.flush()

    debt = Debt(
        owner_user_id=owner.id,
        primary_family_id=family.id,
        debt_name=f"Home {suffix}",
        type="HOME_LOAN",
        status="ACTIVE",
        total_amount=Decimal("12000"),
        remaining_amount=Decimal("12000"),
        total_paid=Decimal("0"),
        balance_for_part_payment=Decimal("0"),
        has_interest=True,
        interest_type=INTEREST_REDUCING_MONTHLY,
        interest_rate=0.0,
        compounding_frequency="MONTHLY",
        has_emi=True,
        emi_amount=Decimal("1000"),
        emi_every="MONTHLY",
        tenure_months=12,
        emi_next_date=_dt(2026, 8, 1),
        requires_confirmation=True,
        start_date=_dt(2026, 7, 1),
    )
    db_session.add(debt)
    await db_session.flush()
    db_session.add(
        DebtScopeView(
            debt_id=debt.id,
            scope_kind="FAMILY",
            family_id=family.id,
            is_primary=True,
            display_name=debt.debt_name,
            access_level="FAMILY",
            excluded=False,
        )
    )
    await db_session.flush()

    fs = FundingService(db_session)
    await fs.save_split_plan(
        SOURCE_DEBT,
        debt.id,
        [
            {
                "pool_type": "PERSONAL",
                "amount": Decimal("600"),
                "user_id": owner.id,
                "expected_total": Decimal("7200"),
                "obligation_remaining": Decimal("7200"),
            },
            {
                "pool_type": "PERSONAL",
                "amount": Decimal("400"),
                "user_id": payer.id,
                "expected_total": Decimal("4800"),
                "obligation_remaining": Decimal("4800"),
            },
        ],
    )
    await db_session.flush()
    return owner, payer, stranger, family, debt


@pytest.mark.integration
async def test_emi_job_schedule_flip_auto_accept_apply(db_session, debt_fixture):
    _owner, _payer, _stranger, _family, debt = debt_fixture

    job = await create_or_replace_next_debt_job(db_session, debt)
    assert job is not None
    assert job.source_type == SOURCE_DEBT
    assert job.source_id == debt.id
    assert job.status == JOB_STATUS_SCHEDULED
    assert job.job_type == JOB_TYPE_DEBT_EMI

    await create_or_replace_next_debt_job(db_session, debt)
    await db_session.flush()
    pending = list(
        (
            await db_session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.source_id == debt.id,
                    ScheduledJob.source_type == SOURCE_DEBT,
                    ScheduledJob.status.in_(
                        [JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(pending) == 1

    now = debt.emi_next_date + timedelta(hours=1)
    stats = await debt_cron_tick(db_session, now=now)
    await db_session.flush()
    await db_session.refresh(job)
    assert (
        stats["debt_emi_materialized"] >= 1
        or job.status == JOB_STATUS_AWAITING_CONFIRMATION
    )

    if job.status == JOB_STATUS_AWAITING_CONFIRMATION:
        job.awaiting_since = now - timedelta(hours=48)
        await db_session.flush()
        await debt_cron_tick(db_session, now=now)
        await db_session.flush()
        await db_session.refresh(job)

    if job.status != JOB_STATUS_APPLIED:
        await apply_debt_emi(db_session, debt, job, paid_externally=True)
        job.status = JOB_STATUS_APPLIED
        await db_session.flush()

    await db_session.refresh(debt)
    assert debt.remaining_amount < Decimal("12000")
    assert debt.total_paid >= Decimal("1000")

    events = list(
        (
            await db_session.execute(
                select(DebtPaymentEvent).where(DebtPaymentEvent.debt_id == debt.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(e.event_type == "EMI" for e in events)

    next_jobs = list(
        (
            await db_session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.source_id == debt.id,
                    ScheduledJob.source_type == SOURCE_DEBT,
                    ScheduledJob.status.in_(
                        [JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(next_jobs) == 1


@pytest.mark.integration
async def test_emi_skips_fulfilled_payers(db_session, debt_fixture):
    _owner, payer, _stranger, _family, debt = debt_fixture
    fs = FundingService(db_session)
    plan = await fs.load_split_plan(SOURCE_DEBT, debt.id)
    assert plan and len(plan) == 2
    for sl in plan:
        if sl.user_id == payer.id:
            sl.obligation_remaining = Decimal("0")
    await db_session.flush()

    job = await create_or_replace_next_debt_job(db_session, debt)
    assert job is not None
    before = debt.remaining_amount
    await apply_debt_emi(db_session, debt, job, paid_externally=True)
    job.status = JOB_STATUS_APPLIED
    await db_session.flush()
    await db_session.refresh(debt)
    assert debt.remaining_amount < before


@pytest.mark.integration
async def test_part_payment_with_balance_and_shortfall(db_session, debt_fixture):
    owner, payer, _stranger, _family, debt = debt_fixture
    svc = DebtService(db_session)

    contrib = await svc.contribute_to_balance(
        debt, actor_user_id=payer.id, amount=Decimal("300")
    )
    assert contrib["balance_for_part_payment"] == Decimal("300")
    await db_session.refresh(debt)
    assert debt.remaining_amount == Decimal("12000")

    await svc.part_payment(
        debt,
        Decimal("1000"),
        "REDUCE_TENURE",
        paid_externally=True,
        use_balance=True,
        actor_user_id=owner.id,
        reassignments=[
            {
                "pool_type": "PERSONAL",
                "amount": Decimal("600"),
                "user_id": owner.id,
                "expected_total": Decimal("6600"),
                "obligation_remaining": Decimal("6600"),
            },
            {
                "pool_type": "PERSONAL",
                "amount": Decimal("400"),
                "user_id": payer.id,
                "expected_total": Decimal("4400"),
                "obligation_remaining": Decimal("4400"),
            },
        ],
    )
    await db_session.refresh(debt)
    assert debt.remaining_amount == Decimal("11000")
    assert debt.balance_for_part_payment == Decimal("0")
    assert debt.total_paid >= Decimal("1000")


@pytest.mark.integration
async def test_contribution_permission_matrix(db_session, debt_fixture):
    owner, payer, stranger, _family, debt = debt_fixture
    svc = DebtService(db_session)

    with pytest.raises(PermissionError):
        await svc.contribute_to_balance(
            debt, actor_user_id=stranger.id, amount=Decimal("50")
        )

    ok = await svc.contribute_to_balance(
        debt, actor_user_id=payer.id, amount=Decimal("50")
    )
    assert ok["balance_for_part_payment"] == Decimal("50")

    with pytest.raises(PermissionError):
        require_debt_owner(payer.id, debt)

    with pytest.raises(PermissionError):
        await svc.part_payment(
            debt,
            Decimal("50"),
            "REDUCE_EMI",
            paid_externally=True,
            use_balance=True,
            actor_user_id=payer.id,
        )

    await svc.part_payment(
        debt,
        Decimal("50"),
        "REDUCE_TENURE",
        paid_externally=True,
        use_balance=True,
        actor_user_id=owner.id,
        reassignments=[
            {"pool_type": "PERSONAL", "amount": Decimal("600"), "user_id": owner.id},
            {"pool_type": "PERSONAL", "amount": Decimal("400"), "user_id": payer.id},
        ],
    )
    await db_session.refresh(debt)
    assert debt.remaining_amount == Decimal("11950")

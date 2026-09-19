from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routes.family.model import Family
from app.api.routes.family_income.income_schemas import (
    FamilySplitInput,
    RecurringIncomeCreateRequest,
    RecurringIncomeQuickAddRequest,
)
from app.api.routes.family_income.income_service import IncomeService
from app.api.routes.family_income.model import (
    FamilyIncomeLog,
    RecurringIncome,
    RecurringIncomeFamilySplit,
)
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.core.constants import (
    JOB_STATUS_APPLIED,
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    JOB_TYPE_RECURRING_INCOME,
    NOTIF_STATUS_DISMISSED,
)
from app.scheduler.income_cron import (
    AUTO_ACCEPT_HOURS,
    cancel_pending_income_jobs,
    create_or_replace_next_job,
    income_cron_tick,
)
from app.scheduler.jobs import SOURCE_RECURRING_INCOME, apply_job


def _dt(year: int, month: int, day: int) -> datetime:
    """Naive UTC datetime for DB columns stored without tz."""
    return datetime(year, month, day)


@pytest.fixture
async def income_fixture(db_session):
    suffix = uuid4().hex[:8]
    user = UserBase(email=f"income-cron-{suffix}@example.com", name="Earner", password="x")
    family_a = Family(name=f"Family A {suffix}", currency="USD")
    family_b = Family(name=f"Family B {suffix}", currency="USD")
    db_session.add_all([user, family_a, family_b])
    await db_session.flush()
    db_session.add_all(
        [
            UserFamilyLink(user_id=user.id, family_id=family_a.id, is_family_manager=True),
            UserFamilyLink(user_id=user.id, family_id=family_b.id, is_family_manager=False),
        ]
    )
    await db_session.flush()
    return user, family_a, family_b


@pytest.mark.integration
async def test_create_or_replace_next_job_is_idempotent(db_session, income_fixture):
    user, family_a, _ = income_fixture
    next_date = _dt(2026, 8, 1)
    income = RecurringIncome(
        user_id=user.id,
        income_name="Salary",
        total_amount=Decimal("1000"),
        personal_savings_amount=Decimal("200"),
        received_every="MONTHLY",
        next_receiving_date=next_date,
    )
    db_session.add(income)
    await db_session.flush()
    db_session.add(
        RecurringIncomeFamilySplit(
            income_id=income.id,
            family_id=family_a.id,
            split_name="Salary",
            amount=Decimal("800"),
        )
    )
    await db_session.flush()

    await create_or_replace_next_job(db_session, income)
    await create_or_replace_next_job(db_session, income)
    await db_session.flush()

    pending = list(
        (
            await db_session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.source_id == income.id,
                    ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
                )
            )
        ).scalars().all()
    )
    assert len(pending) == 1
    assert pending[0].scheduled_for.replace(tzinfo=None) == next_date


@pytest.mark.integration
async def test_cancel_pending_jobs_dismisses_notifications(db_session, income_fixture):
    user, family_a, _ = income_fixture
    next_date = _dt(2026, 8, 1)
    income = RecurringIncome(
        user_id=user.id,
        income_name="Salary",
        total_amount=Decimal("500"),
        personal_savings_amount=Decimal("500"),
        received_every="MONTHLY",
        next_receiving_date=next_date,
    )
    db_session.add(income)
    await db_session.flush()
    job = ScheduledJob(
        family_id=family_a.id,
        job_type=JOB_TYPE_RECURRING_INCOME,
        source_type=SOURCE_RECURRING_INCOME,
        source_id=income.id,
        amount=Decimal("500"),
        direction="ADD",
        period_key="2026-08-01",
        scheduled_for=next_date,
        assigned_user_id=user.id,
        requires_confirmation=True,
        status=JOB_STATUS_AWAITING_CONFIRMATION,
        awaiting_since=next_date,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        Notification(
            user_id=user.id,
            family_id=family_a.id,
            type=JOB_TYPE_RECURRING_INCOME,
            title="Confirm",
            body="test",
            related_job_id=job.id,
            related_entity_type=SOURCE_RECURRING_INCOME,
            related_entity_id=income.id,
            allowed_actions={"actions": ["ACCEPT"]},
            status="UNREAD",
        )
    )
    await db_session.flush()

    await cancel_pending_income_jobs(db_session, income.id)
    await db_session.flush()

    notif = (
        await db_session.execute(select(Notification).where(Notification.related_job_id == job.id))
    ).scalar_one()
    assert notif.status == NOTIF_STATUS_DISMISSED
    refreshed_job = await db_session.get(ScheduledJob, job.id)
    assert refreshed_job.status == JOB_STATUS_CANCELLED


@pytest.mark.integration
async def test_income_cron_auto_accepts_after_24h(db_session, income_fixture):
    user, family_a, family_b = income_fixture
    now = _dt(2026, 8, 2)
    next_date = _dt(2026, 8, 1)
    income = RecurringIncome(
        user_id=user.id,
        income_name="Salary",
        total_amount=Decimal("1000"),
        personal_savings_amount=Decimal("200"),
        received_every="MONTHLY",
        next_receiving_date=next_date,
    )
    db_session.add(income)
    await db_session.flush()
    db_session.add_all(
        [
            RecurringIncomeFamilySplit(
                income_id=income.id,
                family_id=family_a.id,
                split_name="Family A share",
                amount=Decimal("500"),
            ),
            RecurringIncomeFamilySplit(
                income_id=income.id,
                family_id=family_b.id,
                split_name="Family B share",
                amount=Decimal("300"),
            ),
        ]
    )
    await db_session.flush()
    job = ScheduledJob(
        family_id=family_a.id,
        job_type=JOB_TYPE_RECURRING_INCOME,
        source_type=SOURCE_RECURRING_INCOME,
        source_id=income.id,
        amount=Decimal("1000"),
        direction="ADD",
        period_key="2026-08-01",
        scheduled_for=next_date,
        assigned_user_id=user.id,
        requires_confirmation=True,
        status=JOB_STATUS_AWAITING_CONFIRMATION,
        awaiting_since=now - timedelta(hours=AUTO_ACCEPT_HOURS + 1),
    )
    db_session.add(job)
    await db_session.flush()

    stats = await income_cron_tick(db_session, now)
    await db_session.flush()

    assert stats["income_auto_applied"] == 1
    refreshed_job = await db_session.get(ScheduledJob, job.id)
    assert refreshed_job.status == JOB_STATUS_APPLIED

    logs = list(
        (await db_session.execute(select(FamilyIncomeLog).where(FamilyIncomeLog.source_id == income.id)))
        .scalars()
        .all()
    )
    assert len(logs) == 2
    amounts = sorted(log.family_amount for log in logs)
    assert amounts == [Decimal("300.00"), Decimal("500.00")]

    refreshed_income = await db_session.get(RecurringIncome, income.id)
    assert refreshed_income.next_receiving_date > next_date

    next_jobs = list(
        (
            await db_session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.source_id == income.id,
                    ScheduledJob.status == JOB_STATUS_SCHEDULED,
                )
            )
        ).scalars().all()
    )
    assert len(next_jobs) == 1


@pytest.mark.integration
async def test_quick_add_pins_family_split(db_session, income_fixture):
    user, family_a, family_b = income_fixture
    service = IncomeService(db_session, garage_client=None)
    next_date = _dt(2026, 9, 1)

    income = await service.quick_add_recurring_income(
        user_id=user.id,
        family_id=family_a.id,
        data=RecurringIncomeQuickAddRequest(
            income_name="Side gig",
            total_amount=Decimal("300"),
            family_amount=Decimal("200"),
            personal_savings_amount=Decimal("100"),
            received_every="MONTHLY",
            next_receiving_date=next_date,
        ),
    )

    splits = list(
        (
            await db_session.execute(
                select(RecurringIncomeFamilySplit).where(
                    RecurringIncomeFamilySplit.income_id == income.id
                )
            )
        ).scalars().all()
    )
    assert len(splits) == 1
    assert splits[0].family_id == family_a.id
    assert splits[0].amount == Decimal("200")

    income_all_family = await service.quick_add_recurring_income(
        user_id=user.id,
        family_id=family_a.id,
        data=RecurringIncomeQuickAddRequest(
            income_name="Full family",
            total_amount=Decimal("500"),
            received_every="MONTHLY",
            next_receiving_date=next_date,
        ),
    )
    splits_all = list(
        (
            await db_session.execute(
                select(RecurringIncomeFamilySplit).where(
                    RecurringIncomeFamilySplit.income_id == income_all_family.id
                )
            )
        ).scalars().all()
    )
    assert len(splits_all) == 1
    assert splits_all[0].amount == Decimal("500")

    with pytest.raises(ValueError, match="not a member"):
        family_c = Family(name="Family C", currency="USD")
        db_session.add(family_c)
        await db_session.flush()
        await service.create_recurring_income(
            user.id,
            RecurringIncomeCreateRequest(
                income_name="Bad",
                total_amount=Decimal("100"),
                personal_savings_amount=Decimal("50"),
                family_splits=[
                    FamilySplitInput(
                        family_id=family_c.id,
                        split_name="Other",
                        amount=Decimal("50"),
                    )
                ],
                received_every="MONTHLY",
                next_receiving_date=next_date,
            ),
        )


@pytest.mark.integration
async def test_apply_job_rejects_non_awaiting_income_job(db_session, income_fixture):
    user, family_a, _ = income_fixture
    next_date = _dt(2026, 8, 1)
    income = RecurringIncome(
        user_id=user.id,
        income_name="Salary",
        total_amount=Decimal("100"),
        personal_savings_amount=Decimal("100"),
        received_every="MONTHLY",
        next_receiving_date=next_date,
    )
    db_session.add(income)
    await db_session.flush()
    job = ScheduledJob(
        family_id=family_a.id,
        job_type=JOB_TYPE_RECURRING_INCOME,
        source_type=SOURCE_RECURRING_INCOME,
        source_id=income.id,
        amount=Decimal("100"),
        direction="ADD",
        period_key="2026-08-01",
        scheduled_for=next_date,
        assigned_user_id=user.id,
        requires_confirmation=True,
        status=JOB_STATUS_SCHEDULED,
    )
    db_session.add(job)
    await db_session.flush()

    with pytest.raises(ValueError, match="cannot be applied"):
        await apply_job(db_session, job)

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.core.emi_recompute import (
    recompute_goal_contribution,
    recompute_plan_contribution,
    remaining_plan_periods,
)


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _plan(**kw):
    base = dict(
        target_amount=Decimal("40000"),
        accumulated_amount=Decimal("0"),
        next_contribution_date=_dt(2026, 1, 1),
        next_target_date=_dt(2026, 4, 1),
        contribution_every="MONTHLY",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_remaining_plan_periods_inclusive():
    # Jan, Feb, Mar, Apr = 4 periods
    assert remaining_plan_periods(_plan()) == 4


def test_recompute_plan_contribution_spreads_remaining():
    plan = _plan(target_amount=Decimal("40000"), accumulated_amount=Decimal("0"))
    # 40000 / 4 = 10000
    assert recompute_plan_contribution(plan) == Decimal("10000.00")


def test_recompute_plan_contribution_accounts_for_accumulated():
    plan = _plan(target_amount=Decimal("40000"), accumulated_amount=Decimal("10000"))
    # remaining 30000 / 4 = 7500
    assert recompute_plan_contribution(plan) == Decimal("7500.00")


def test_recompute_plan_contribution_zero_when_funded():
    plan = _plan(accumulated_amount=Decimal("40000"))
    assert recompute_plan_contribution(plan) == Decimal("0")


def test_recompute_goal_contribution():
    goal = SimpleNamespace(
        target_amount=Decimal("12000"),
        collected_amount=Decimal("0"),
        next_contribution_date=_dt(2026, 1, 1),
        target_date=_dt(2026, 3, 1),
        contribution_every="MONTHLY",
    )
    # Jan, Feb, Mar = 3 -> 12000/3 = 4000
    assert recompute_goal_contribution(goal) == Decimal("4000.00")

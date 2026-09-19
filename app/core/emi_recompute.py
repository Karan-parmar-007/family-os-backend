"""EMI / sinking-fund recompute helpers (Family System V2).

Pure functions that compute how many contribution periods remain for a savings
plan or goal and the recomputed per-period amount needed to still hit the
target on time.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core.date_advance import advance_next_date

_MAX_PERIODS = 2000  # guard against runaway loops from bad data
_CENTS = Decimal("0.01")


def _to_decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _count_periods(
    start: datetime | None, end: datetime | None, every: str | None
) -> int:
    """Number of scheduled dates in [start, end] stepping by ``every``."""
    if start is None or end is None:
        return 0
    count = 0
    cursor = start
    for _ in range(_MAX_PERIODS):
        if cursor > end:
            break
        count += 1
        cursor = advance_next_date(cursor, every=every)
    return count


def remaining_plan_periods(plan) -> int:
    return _count_periods(
        plan.next_contribution_date, plan.next_target_date, plan.contribution_every
    )


def recompute_plan_contribution(plan) -> Decimal:
    """Per-period contribution needed to reach ``target_amount`` by target date."""
    remaining = _to_decimal(plan.target_amount) - _to_decimal(plan.accumulated_amount)
    if remaining <= 0:
        return Decimal("0")
    periods = remaining_plan_periods(plan)
    if periods <= 0:
        return remaining.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return (remaining / periods).quantize(_CENTS, rounding=ROUND_HALF_UP)


def remaining_goal_periods(goal) -> int:
    return _count_periods(
        goal.next_contribution_date, goal.target_date, goal.contribution_every
    )


def recompute_goal_contribution(goal) -> Decimal:
    remaining = _to_decimal(goal.target_amount) - _to_decimal(goal.collected_amount)
    if remaining <= 0:
        return Decimal("0")
    periods = remaining_goal_periods(goal)
    if periods <= 0:
        return remaining.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return (remaining / periods).quantize(_CENTS, rounding=ROUND_HALF_UP)

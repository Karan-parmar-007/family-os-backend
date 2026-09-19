from datetime import datetime, timezone

from app.core.date_advance import add_months, advance_next_date


def test_add_months_end_of_month():
    dt = datetime(2026, 1, 31, tzinfo=timezone.utc)
    advanced = add_months(dt, 1)
    assert advanced.month == 2
    assert advanced.day == 28


def test_advance_monthly():
    dt = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert advance_next_date(dt, every="MONTHLY").month == 2


def test_advance_weekly():
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert advance_next_date(dt, every="WEEKLY").day == 8


def test_advance_custom_interval_days():
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert advance_next_date(dt, interval_days=10).day == 11


def test_advance_combined_interval_months_and_days():
    dt = datetime(2026, 1, 15, tzinfo=timezone.utc)
    advanced = advance_next_date(dt, interval_months=1, interval_days=6)
    assert advanced.month == 2
    assert advanced.day == 21


def test_advance_combined_interval_years_months_days():
    dt = datetime(2026, 1, 10, tzinfo=timezone.utc)
    advanced = advance_next_date(dt, interval_years=1, interval_months=2, interval_days=5)
    assert advanced.year == 2027
    assert advanced.month == 3
    assert advanced.day == 15

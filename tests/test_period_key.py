from datetime import datetime, timezone

from app.core.period_key import period_key_for_date


def test_period_key_monthly():
    when = datetime(2026, 7, 15, tzinfo=timezone.utc)
    assert period_key_for_date(when, every="MONTHLY") == "2026-07"


def test_period_key_yearly():
    when = datetime(2026, 7, 15, tzinfo=timezone.utc)
    assert period_key_for_date(when, every="YEARLY") == "2026"


def test_period_key_weekly():
    when = datetime(2026, 7, 6, tzinfo=timezone.utc)
    assert period_key_for_date(when, every="WEEKLY") == "2026-W28"


def test_period_key_daily():
    when = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    assert period_key_for_date(when, every="DAILY") == "2026-07-06"

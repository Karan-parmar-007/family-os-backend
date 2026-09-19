from datetime import datetime, timedelta, timezone

from app.api.routes.upcoming.upcoming_service import _project


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_project_none_start_returns_empty():
    assert _project(None, _dt(2026, 12, 1), every="MONTHLY") == []


def test_project_monthly_within_horizon():
    start = _dt(2026, 1, 1)
    end = _dt(2026, 3, 15)
    dates = _project(start, end, every="MONTHLY")
    assert dates == [_dt(2026, 1, 1), _dt(2026, 2, 1), _dt(2026, 3, 1)]


def test_project_stops_at_horizon():
    start = _dt(2026, 1, 1)
    end = _dt(2026, 1, 1)
    assert _project(start, end, every="MONTHLY") == [_dt(2026, 1, 1)]


def test_project_weekly():
    start = _dt(2026, 1, 1)
    end = _dt(2026, 1, 20)
    dates = _project(start, end, every="WEEKLY")
    assert dates == [_dt(2026, 1, 1), _dt(2026, 1, 8), _dt(2026, 1, 15)]


def test_project_is_capped():
    start = _dt(2000, 1, 1)
    end = _dt(2100, 1, 1)
    # capped at 60 occurrences regardless of huge horizon
    assert len(_project(start, end, every="MONTHLY")) == 60


def test_project_naive_start_is_coerced_to_utc():
    start = datetime(2026, 1, 1)  # naive
    end = datetime.now(timezone.utc) + timedelta(days=1)
    # should not raise a naive/aware comparison error
    result = _project(start, end, every="YEARLY")
    assert isinstance(result, list)

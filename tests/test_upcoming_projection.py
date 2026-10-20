from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.routes.upcoming.upcoming_service import _MAX_OCCURRENCES, _project_rule


def _dt(y, m, d):
    return datetime(y, m, d, 12, 30, tzinfo=timezone.utc)


def _rule(start, *, every="MONTHLY", every_n=1, end_at=None, max_runs=None, run_count=0, anchor_day=None):
    return SimpleNamespace(
        next_run_at=start,
        frequency=every,
        every_n=every_n,
        end_at=end_at,
        max_runs=max_runs,
        run_count=run_count,
        anchor_day=anchor_day,
    )


def test_monthly_within_horizon():
    dates = _project_rule(_rule(_dt(2026, 1, 1)), _dt(2026, 3, 15), "UTC")
    assert [d.date().isoformat() for d in dates] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert all(d.hour == 18 for d in dates[1:])


def test_month_end_anchor_survives_february():
    dates = _project_rule(_rule(_dt(2026, 1, 31), anchor_day=31), _dt(2026, 4, 30), "UTC")
    assert [d.day for d in dates] == [31, 28, 31]


def test_every_two_weeks():
    dates = _project_rule(_rule(_dt(2026, 1, 1), every="WEEKLY", every_n=2), _dt(2026, 2, 1), "UTC")
    assert [d.day for d in dates] == [1, 15, 29]


def test_max_runs_counts_past_runs():
    dates = _project_rule(_rule(_dt(2026, 1, 1), max_runs=5, run_count=3), _dt(2027, 1, 1), "UTC")
    assert len(dates) == 2


def test_end_date_stops_projection():
    dates = _project_rule(_rule(_dt(2026, 1, 1), end_at=_dt(2026, 2, 15)), _dt(2027, 1, 1), "UTC")
    assert len(dates) == 2


def test_projection_is_capped():
    dates = _project_rule(_rule(_dt(2000, 1, 1)), _dt(2100, 1, 1), "UTC")
    assert len(dates) == _MAX_OCCURRENCES

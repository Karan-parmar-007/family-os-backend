"""Snap datetimes to 18:00 in a scope timezone, stored as UTC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Kolkata"


def _zone(tz_name: str | None) -> ZoneInfo:
    name = (tz_name or DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TZ)


def at_eighteen_utc(when: datetime, tz_name: str | None) -> datetime:
    """Use the calendar date of ``when`` at 18:00 in ``tz_name``, as UTC."""
    tz = _zone(tz_name)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(tz)
    target = local.replace(hour=18, minute=0, second=0, microsecond=0)
    return target.astimezone(timezone.utc)


def next_eighteen_utc(after: datetime, tz_name: str | None) -> datetime:
    """First 18:00 in ``tz_name`` strictly after ``after``."""
    tz = _zone(tz_name)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    local = after.astimezone(tz)
    target = local.replace(hour=18, minute=0, second=0, microsecond=0)
    if local >= target:
        target = target + timedelta(days=1)
    return target.astimezone(timezone.utc)

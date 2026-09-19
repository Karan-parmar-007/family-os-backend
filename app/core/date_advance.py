"""Advance recurring next_* dates with custom intervals and standard presets."""

import re
from datetime import datetime, timedelta


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def advance_next_date(
    current: datetime,
    *,
    every: str | None = None,
    interval_days: int | None = None,
    interval_months: int | None = None,
    interval_years: int | None = None,
) -> datetime:
    if interval_days or interval_months or interval_years:
        result = current
        total_months = (interval_years or 0) * 12 + (interval_months or 0)
        if total_months:
            result = add_months(result, total_months)
        if interval_days:
            result = result + timedelta(days=interval_days)
        return result

    raw_freq = (every or "MONTHLY").strip().upper()

    # Match custom patterns like EVERY_7_DAYS, CUSTOM_21_DAYS, 14_DAYS, EVERY_2_WEEKS, EVERY_3_MONTHS, EVERY_1_YEARS
    custom_match = re.match(
        r"^(?:EVERY_|CUSTOM_)?(\d+)[_\s]*(DAY|DAYS|WEEK|WEEKS|MONTH|MONTHS|YEAR|YEARS)$",
        raw_freq,
        re.IGNORECASE,
    )
    if custom_match:
        count = int(custom_match.group(1))
        unit = custom_match.group(2).upper()
        if unit.startswith("DAY"):
            return current + timedelta(days=count)
        if unit.startswith("WEEK"):
            return current + timedelta(weeks=count)
        if unit.startswith("MONTH"):
            return add_months(current, count)
        if unit.startswith("YEAR"):
            return add_months(current, count * 12)

    # Standard presets
    if raw_freq in ("DAILY", "DAY"):
        return current + timedelta(days=1)
    if raw_freq in ("WEEKLY", "WEEK"):
        return current + timedelta(weeks=1)
    if raw_freq in ("BIWEEKLY", "BI_WEEKLY", "FORTNIGHTLY"):
        return current + timedelta(weeks=2)
    if raw_freq in ("MONTHLY", "MONTH"):
        return add_months(current, 1)
    if raw_freq in ("QUARTERLY", "QUARTER"):
        return add_months(current, 3)
    if raw_freq in ("SEMIANNUAL", "SEMI_ANNUAL", "HALF_YEARLY"):
        return add_months(current, 6)
    if raw_freq in ("YEARLY", "ANNUAL", "YEAR"):
        return add_months(current, 12)

    return add_months(current, 1)

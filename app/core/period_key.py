"""Period key generation for scheduler idempotency (Family System V2)."""

from datetime import datetime


def period_key_for_date(when: datetime, *, every: str | None = None) -> str:
    """Return a stable period key for the given occurrence date."""
    freq = (every or "MONTHLY").upper()
    if freq == "YEARLY":
        return f"{when.year}"
    if freq == "WEEKLY":
        iso = when.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if freq == "DAILY":
        return when.strftime("%Y-%m-%d")
    return when.strftime("%Y-%m")

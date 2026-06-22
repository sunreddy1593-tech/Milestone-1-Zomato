"""Opening-hours helpers for ``open_now`` filtering."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from app.data.models import DayHours

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def parse_time(value: str) -> int:
    """Parse ``HH:MM`` into minutes since midnight."""
    hour_str, minute_str = value.strip().split(":", 1)
    return int(hour_str) * 60 + int(minute_str)


def is_open_at(open_time: str, close_time: str, minutes_now: int) -> bool:
    """Return whether a venue is open at ``minutes_now`` for one day's hours.

    Handles overnight hours when ``close`` is earlier than ``open`` (e.g. 18:00–02:00).
    """
    open_minutes = parse_time(open_time)
    close_minutes = parse_time(close_time)

    if close_minutes > open_minutes:
        return open_minutes <= minutes_now < close_minutes
    if close_minutes == open_minutes:
        return False
    return minutes_now >= open_minutes or minutes_now < close_minutes


def is_open_now(
    opening_hours: dict[str, DayHours],
    *,
    now: datetime | None = None,
    timezone: str = "Asia/Kolkata",
) -> bool:
    """Return whether a restaurant is open at ``now`` in the given timezone.

    Checks today's hours and yesterday's overnight spill (e.g. Friday 18:00–02:00
    still open at Saturday 01:00).
    """
    if not opening_hours:
        return False

    tz = ZoneInfo(timezone)
    current = now.astimezone(tz) if now is not None else datetime.now(tz)
    minutes_now = current.hour * 60 + current.minute
    weekday_idx = current.weekday()

    today_key = WEEKDAYS[weekday_idx]
    today_hours = opening_hours.get(today_key)
    if today_hours and is_open_at(today_hours.open, today_hours.close, minutes_now):
        return True

    yesterday_key = WEEKDAYS[(weekday_idx - 1) % 7]
    yesterday_hours = opening_hours.get(yesterday_key)
    if yesterday_hours:
        open_minutes = parse_time(yesterday_hours.open)
        close_minutes = parse_time(yesterday_hours.close)
        if close_minutes <= open_minutes and minutes_now < close_minutes:
            return True

    return False

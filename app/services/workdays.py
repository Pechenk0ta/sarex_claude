"""Working-day arithmetic with the production calendar (TZ 3.7, 4.3).

A day is a working day if it is Mon–Fri, unless the `holidays` table says otherwise.
Pure functions take the calendar exceptions as a mapping, so they are testable without a DB;
`load_calendar` reads that mapping from the database.
"""

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Holiday

Calendar = Mapping[date, bool]
"""Exceptions to the normal week: date -> is_workday."""

_MAX_SCAN_DAYS = 3660  # guard against a calendar that marks everything as a day off


def is_workday(day: date, calendar: Calendar) -> bool:
    if day in calendar:
        return calendar[day]
    return day.weekday() < 5


def add_workdays(start: date, count: int, calendar: Calendar) -> date:
    """The date that is `count` working days after `start` (`start` itself is not counted).

    Sent on Fri 11.09.2026 with a 10-working-day deadline -> Fri 25.09.2026.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    day = start
    remaining = count
    for _ in range(_MAX_SCAN_DAYS):
        if remaining == 0:
            return day
        day += timedelta(days=1)
        if is_workday(day, calendar):
            remaining -= 1
    raise ValueError("calendar has no working days in range")


def workdays_between(start: date, end: date, calendar: Calendar) -> int:
    """Working days in the interval (start, end]: how many have passed since `start`.

    Sent on 11.09.2026, checked on Sat 26.09.2026 -> 10.
    """
    if end <= start:
        return 0
    return sum(
        1
        for offset in range(1, (end - start).days + 1)
        if is_workday(start + timedelta(days=offset), calendar)
    )


def local_date(moment: datetime, timezone: str) -> date:
    """Calendar date of an aware UTC timestamp in the application timezone."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime: all timestamps must be timezone-aware")
    return moment.astimezone(ZoneInfo(timezone)).date()


async def load_calendar(session: AsyncSession, start: date, end: date) -> dict[date, bool]:
    """Calendar exceptions for [start, end] from the `holidays` table."""
    rows = await session.execute(
        select(Holiday.date, Holiday.is_workday).where(Holiday.date.between(start, end))
    )
    return {row.date: row.is_workday for row in rows}

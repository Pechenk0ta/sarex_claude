"""The daily job's decision for one notification (TZ 4.3), without a database."""

from datetime import UTC, date, datetime

import pytest

from app.config import Settings
from app.models import EventType, Notification, NotificationStatus
from app.services.reminders import next_action
from app.worker import catch_up_needed

SETTINGS = Settings(_env_file=None)
SENT = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)  # Fri 11.09 10:00 Moscow time
DEADLINE = datetime(2026, 9, 25, 15, 0, tzinfo=UTC)  # Fri 25.09 18:00


def _notification(**changes: object) -> Notification:
    fields: dict[str, object] = {
        "status": NotificationStatus.SENT,
        "needs_manual_review": False,
        "reminder_count": 0,
        "sent_at": SENT,
        "deadline_at": DEADLINE,
    }
    fields.update(changes)
    return Notification(**fields)


def _action(today: date, **changes: object) -> EventType | None:
    return next_action(_notification(**changes), today, {}, SETTINGS)


@pytest.mark.parametrize(
    ("today", "reminders_sent", "expected"),
    [
        (date(2026, 9, 11), 0, None),  # the sending day
        (date(2026, 9, 14), 0, EventType.REMINDER_1),  # Mon: 1st working day
        (date(2026, 9, 14), 1, None),  # the same day again
        (date(2026, 9, 15), 1, None),
        (date(2026, 9, 16), 1, EventType.REMINDER_3),  # Wed: 3rd working day
        (date(2026, 9, 16), 0, EventType.REMINDER_3),  # missed days: one letter, not two
        (date(2026, 9, 17), 2, None),
        (date(2026, 9, 25), 2, None),  # deadline day: still in time
        (date(2026, 9, 28), 2, EventType.ESCALATED),
        (date(2026, 9, 28), 0, EventType.ESCALATED),  # no reminders after the deadline
    ],
)
def test_schedule(today: date, reminders_sent: int, expected: EventType | None) -> None:
    assert _action(today, reminder_count=reminders_sent) is expected


@pytest.mark.parametrize(
    "status",
    [
        NotificationStatus.ACKNOWLEDGED,
        NotificationStatus.HAS_QUESTIONS,
        NotificationStatus.REJECTED,
        NotificationStatus.ESCALATED,
    ],
)
def test_answered_or_escalated_are_left_alone(status: NotificationStatus) -> None:
    assert _action(date(2026, 9, 28), status=status) is None


def test_reply_waiting_for_coordinator_stops_reminders() -> None:
    assert _action(date(2026, 9, 14), needs_manual_review=True) is None


def test_holiday_moves_the_first_reminder() -> None:
    calendar = {date(2026, 9, 14): False}
    notification = _notification()
    assert next_action(notification, date(2026, 9, 14), calendar, SETTINGS) is None
    assert next_action(notification, date(2026, 9, 15), calendar, SETTINGS) is (
        EventType.REMINDER_1
    )


def test_short_deadline_escalates_without_second_reminder() -> None:
    short = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)  # Tue 15.09
    assert _action(date(2026, 9, 15), reminder_count=1, deadline_at=short) is None
    assert _action(date(2026, 9, 16), reminder_count=1, deadline_at=short) is (EventType.ESCALATED)


def test_intervals_come_from_settings() -> None:
    settings = Settings(_env_file=None, first_reminder_workdays=2, second_reminder_workdays=4)
    assert next_action(_notification(), date(2026, 9, 14), {}, settings) is None
    assert next_action(_notification(), date(2026, 9, 15), {}, settings) is EventType.REMINDER_1


def test_catch_up_only_during_the_working_day() -> None:
    assert catch_up_needed(datetime(2026, 9, 14, 11, 30)) is True
    assert catch_up_needed(datetime(2026, 9, 14, 8, 59)) is False
    assert catch_up_needed(datetime(2026, 9, 14, 21, 0)) is False

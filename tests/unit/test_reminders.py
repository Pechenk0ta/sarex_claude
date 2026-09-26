"""The daily job's decision for one notification (TZ 4.3), without a database."""

from datetime import UTC, date, datetime

import pytest

from app.config import Settings
from app.models import EventType, Notification, NotificationStatus
from app.services.reminders import next_actions
from app.worker import catch_up_needed

SETTINGS = Settings(_env_file=None)
SENT = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)  # Fri 11.09 10:00 Moscow time
DEADLINE = datetime(2026, 9, 25, 15, 0, tzinfo=UTC)  # Fri 25.09 18:00

R1, R3, ESC = EventType.REMINDER_1, EventType.REMINDER_3, EventType.ESCALATED
SENT_STATUS, ESCALATED = NotificationStatus.SENT, NotificationStatus.ESCALATED


def _notification(**changes: object) -> Notification:
    fields: dict[str, object] = {
        "status": SENT_STATUS,
        "needs_manual_review": False,
        "reminder_count": 0,
        "sent_at": SENT,
        "deadline_at": DEADLINE,
    }
    fields.update(changes)
    return Notification(**fields)


def _actions(today: date, settings: Settings = SETTINGS, **changes: object) -> list[EventType]:
    return next_actions(_notification(**changes), today, {}, settings)


@pytest.mark.parametrize(
    ("today", "status", "reminders_sent", "expected"),
    [
        (date(2026, 9, 14), SENT_STATUS, 0, []),  # nothing before the deadline
        (date(2026, 9, 16), SENT_STATUS, 0, []),
        (date(2026, 9, 25), SENT_STATUS, 0, []),  # the deadline day is still in time
        (date(2026, 9, 28), SENT_STATUS, 0, [R1, ESC]),  # Mon: 1st working day of delay
        (date(2026, 9, 28), ESCALATED, 1, []),  # the same day again
        (date(2026, 9, 29), ESCALATED, 1, []),
        (date(2026, 9, 30), ESCALATED, 1, [R3]),  # Wed: 3rd working day of delay
        (date(2026, 10, 1), ESCALATED, 2, []),
        (date(2026, 9, 30), SENT_STATUS, 0, [R3, ESC]),  # missed days: one reminder, not two
    ],
)
def test_schedule(
    today: date, status: NotificationStatus, reminders_sent: int, expected: list[EventType]
) -> None:
    assert _actions(today, status=status, reminder_count=reminders_sent) == expected


@pytest.mark.parametrize(
    "status",
    [
        NotificationStatus.ACKNOWLEDGED,
        NotificationStatus.HAS_QUESTIONS,
        NotificationStatus.REJECTED,
    ],
)
def test_answered_are_left_alone(status: NotificationStatus) -> None:
    assert _actions(date(2026, 9, 28), status=status) == []


def test_reply_waiting_for_coordinator_stops_reminders() -> None:
    assert _actions(date(2026, 9, 28), needs_manual_review=True) == []


def test_holiday_moves_the_first_reminder() -> None:
    calendar = {date(2026, 9, 28): False}
    notification = _notification()
    assert next_actions(notification, date(2026, 9, 28), calendar, SETTINGS) == []
    assert next_actions(notification, date(2026, 9, 29), calendar, SETTINGS) == [R1, ESC]


def test_intervals_come_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        first_reminder_workdays=2,
        second_reminder_workdays=4,
        escalation_workdays=4,
    )
    assert _actions(date(2026, 9, 28), settings) == []
    assert _actions(date(2026, 9, 29), settings) == [R1]
    assert _actions(date(2026, 10, 1), settings, reminder_count=1) == [R3, ESC]


def test_catch_up_only_during_the_working_day() -> None:
    assert catch_up_needed(datetime(2026, 9, 14, 11, 30)) is True
    assert catch_up_needed(datetime(2026, 9, 14, 8, 59)) is False
    assert catch_up_needed(datetime(2026, 9, 14, 21, 0)) is False

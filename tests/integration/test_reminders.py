"""Daily reminders and escalation on a real database (TZ 4.3)."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    EventType,
    Holiday,
    Notification,
    NotificationEvent,
    NotificationStatus,
    User,
)
from app.services.notifications import change_deadline, create_mailing, set_status
from app.services.reminders import RunResult, run_reminders
from tests.integration.factories import project_with_contractors

SETTINGS = Settings(
    _env_file=None,
    mail_address="rd@company.ru",
    secret_key="k" * 32,
    app_base_url="https://rd.example.ru",
)
SENT = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)  # Fri 11.09 10:00 Moscow time
LINK = "https://sarex.example.ru/project/sd-3/docs/OV-rev1"


def _at(day: date) -> datetime:
    """The job's usual time: 09:00 Moscow time."""
    return datetime(day.year, day.month, day.day, 6, 0, tzinfo=UTC)


async def _mailing(
    session: AsyncSession, contractors: int = 3, deadline: date | None = None
) -> tuple[list[Notification], User]:
    project, corpus, people, user = await project_with_contractors(session, contractors)
    result = await create_mailing(
        session,
        SETTINGS,
        initiator=user,
        project_id=project.id,
        corpus_id=corpus.id,
        sarex_link=LINK,
        message="Листы 12–14",
        contractor_ids=[c.id for c in people],
        deadline=deadline,
        now=SENT,
    )
    return result.notifications, user


async def _run(session: AsyncSession, day: date) -> RunResult:
    return await run_reminders(session, SETTINGS, now=_at(day))


async def _events(session: AsyncSession, notification: Notification) -> list[NotificationEvent]:
    return list(
        await session.scalars(
            select(NotificationEvent)
            .where(NotificationEvent.notification_id == notification.id)
            .order_by(NotificationEvent.created_at)
        )
    )


async def test_full_cycle_reminder_reminder_escalation(session: AsyncSession) -> None:
    notifications, _ = await _mailing(session)
    first = notifications[0]

    monday = await _run(session, date(2026, 9, 14))
    assert (monday.reminders, monday.escalated, len(monday.letters)) == (3, 0, 3)
    assert first.reminder_count == 1
    assert (await _run(session, date(2026, 9, 14))).letters == []  # second run, same day
    assert (await _run(session, date(2026, 9, 15))).letters == []
    wednesday = await _run(session, date(2026, 9, 16))
    assert wednesday.reminders == 3
    assert first.reminder_count == 2
    for day in (17, 18, 21, 22, 23, 24, 25):
        assert (await _run(session, date(2026, 9, day))).letters == [], day
    saturday = await _run(session, date(2026, 9, 26))
    assert saturday.skipped_day_off

    escalation = await _run(session, date(2026, 9, 28))
    assert (escalation.reminders, escalation.escalated, len(escalation.letters)) == (0, 3, 1)
    assert {n.status for n in notifications} == {NotificationStatus.ESCALATED}
    assert first.escalated_at == _at(date(2026, 9, 28))
    assert (await _run(session, date(2026, 9, 28))).letters == []
    assert (await _run(session, date(2026, 9, 29))).letters == []

    types = [e.type for e in await _events(session, first)]
    assert types == [
        EventType.SENT,
        EventType.REMINDER_1,
        EventType.REMINDER_3,
        EventType.ESCALATED,
    ]


async def test_reminder_letter_repeats_the_notification_in_the_same_thread(
    session: AsyncSession,
) -> None:
    [notification], _ = await _mailing(session, contractors=1)
    result = await _run(session, date(2026, 9, 14))

    sent, reminder = await _events(session, notification)
    assert reminder.id in result.letters
    assert reminder.payload["delivery"] == "pending"
    assert reminder.payload["in_reply_to"] == sent.payload["message_id"]
    assert reminder.payload["reply_to"] == sent.payload["reply_to"]
    assert reminder.payload["subject"] == "Повторно: " + sent.payload["subject"]
    assert "Повторное уведомление" in reminder.payload["text"]
    assert "Листы 12–14" in reminder.payload["text"]
    assert "/ack/" in reminder.payload["text"]
    assert notification.last_reminder_at == _at(date(2026, 9, 14))


async def test_one_escalation_letter_per_mailing_to_the_project_manager(
    session: AsyncSession,
) -> None:
    notifications, user = await _mailing(session)
    await set_status(
        session, SETTINGS, notifications[1], NotificationStatus.ACKNOWLEDGED, user=user
    )

    result = await _run(session, date(2026, 9, 28))

    assert result.escalated == 2
    [letter_id] = result.letters
    events = [
        e
        for n in (notifications[0], notifications[2])
        for e in await _events(session, n)
        if e.type is EventType.ESCALATED
    ]
    [letter] = [e for e in events if e.id == letter_id]
    [copy] = [e for e in events if e.id != letter_id]
    assert letter.payload["to"] == "pm@company.ru"
    assert letter.payload["delivery"] == "pending"
    assert letter.payload["subject"].startswith("Эскалация: нет подтверждения РД")
    text = letter.payload["text"]
    assert "ООО «П0»" in text and "ООО «П2»" in text and "ООО «П1»" not in text
    assert "11 р.д. без ответа" in text  # 11.09 → 28.09
    assert f"https://rd.example.ru/notifications/{notifications[0].id}" in text
    assert "delivery" not in copy.payload  # the letter goes out once
    assert copy.payload["letter_event_id"] == str(letter_id)
    assert copy.raw_content == letter.raw_content
    assert notifications[1].status is NotificationStatus.ACKNOWLEDGED


async def test_answered_contractor_gets_no_reminder(session: AsyncSession) -> None:
    notifications, user = await _mailing(session)
    await set_status(
        session, SETTINGS, notifications[0], NotificationStatus.ACKNOWLEDGED, user=user
    )
    await set_status(
        session, SETTINGS, notifications[1], NotificationStatus.HAS_QUESTIONS, user=user
    )
    notifications[2].needs_manual_review = True

    result = await _run(session, date(2026, 9, 14))

    assert result.reminders == 0
    assert all(n.reminder_count == 0 for n in notifications)


async def test_holiday_is_skipped_and_moves_the_reminder(session: AsyncSession) -> None:
    session.add(Holiday(date=date(2026, 9, 14), is_workday=False))
    await session.flush()
    [notification], _ = await _mailing(session, contractors=1)

    assert (await _run(session, date(2026, 9, 14))).skipped_day_off
    assert (await _run(session, date(2026, 9, 15))).reminders == 1
    assert notification.reminder_count == 1


async def test_short_deadline_escalates_after_first_reminder(session: AsyncSession) -> None:
    [notification], _ = await _mailing(session, contractors=1, deadline=date(2026, 9, 15))

    assert (await _run(session, date(2026, 9, 14))).reminders == 1
    assert (await _run(session, date(2026, 9, 15))).letters == []  # deadline day
    result = await _run(session, date(2026, 9, 16))
    assert (result.reminders, result.escalated) == (0, 1)
    assert notification.reminder_count == 1


async def test_extended_deadline_escalates_again_later(session: AsyncSession) -> None:
    [notification], user = await _mailing(session, contractors=1)
    await _run(session, date(2026, 9, 28))
    assert notification.status is NotificationStatus.ESCALATED

    await change_deadline(
        session, SETTINGS, notification, date(2026, 10, 2), user=user, now=_at(date(2026, 9, 28))
    )
    assert notification.status is NotificationStatus.SENT
    # No reminders were sent before the escalation: the contractor is reminded of the new date.
    reminder = await _run(session, date(2026, 10, 2))
    assert reminder.reminders == 1
    [letter] = [e for e in await _events(session, notification) if e.id in reminder.letters]
    assert "02.10.2026" in letter.payload["subject"]
    result = await _run(session, date(2026, 10, 5))
    assert result.escalated == 1
    escalations = [e for e in await _events(session, notification) if e.type is EventType.ESCALATED]
    assert len(escalations) == 2


async def test_missed_days_send_one_reminder(session: AsyncSession) -> None:
    [notification], _ = await _mailing(session, contractors=1)

    result = await _run(session, date(2026, 9, 17))  # worker was down Mon–Wed

    assert result.reminders == 1
    assert notification.reminder_count == 2
    types = [e.type for e in await _events(session, notification)]
    assert types == [EventType.SENT, EventType.REMINDER_3]
    assert (await _run(session, date(2026, 9, 17) + timedelta(days=1))).letters == []

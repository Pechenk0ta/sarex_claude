from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contractor,
    Corpus,
    EventType,
    Holiday,
    Notification,
    NotificationEvent,
    NotificationStatus,
    Project,
    ProjectContractor,
    User,
    UserRole,
)
from app.services.workdays import add_workdays, load_calendar


async def _notification(session: AsyncSession) -> Notification:
    project = Project(name="Тестовый проект", project_manager_email="pm@example.ru")
    corpus = Corpus(project=project, name="Корпус 1")
    contractor = Contractor(name="ООО «Тест»", email="test@example.ru")
    user = User(email="c@example.ru", full_name="Координатор", role=UserRole.COORDINATOR)
    session.add_all([project, corpus, contractor, user])
    await session.flush()
    session.add(ProjectContractor(project_id=project.id, contractor_id=contractor.id))
    notification = Notification(
        project_id=project.id,
        corpus_id=corpus.id,
        contractor_id=contractor.id,
        sarex_link="https://sarex.example.ru/doc",
        reply_token="tok-1",
        initiator_id=user.id,
        sent_at=datetime(2026, 9, 11, 7, tzinfo=UTC),
        deadline_at=datetime(2026, 9, 25, 15, tzinfo=UTC),
    )
    session.add(notification)
    await session.flush()
    return notification


async def test_notification_defaults(session: AsyncSession) -> None:
    notification = await _notification(session)
    await session.refresh(notification)

    assert notification.status is NotificationStatus.SENT
    assert notification.reminder_count == 0
    assert notification.needs_manual_review is False
    assert notification.channel == "email"


async def test_events_are_kept_in_order_with_jsonb_payload(session: AsyncSession) -> None:
    notification = await _notification(session)
    session.add_all(
        [
            NotificationEvent(
                notification_id=notification.id,
                type=EventType.REMINDER_1,
                created_at=datetime(2026, 9, 14, 6, tzinfo=UTC),
            ),
            NotificationEvent(
                notification_id=notification.id,
                type=EventType.SENT,
                raw_content="Добрый день!",
                payload={"to": "test@example.ru"},
                created_at=datetime(2026, 9, 11, 7, tzinfo=UTC),
            ),
        ]
    )
    await session.flush()
    await session.refresh(notification, ["events"])

    assert [e.type for e in notification.events] == [EventType.SENT, EventType.REMINDER_1]
    assert notification.events[0].payload == {"to": "test@example.ru"}


async def test_unknown_status_rejected_by_database(session: AsyncSession) -> None:
    notification = await _notification(session)
    with pytest.raises(IntegrityError, match="ck_notifications_notification_status"):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE notifications SET status = 'lost' WHERE id = :id"),
                {"id": notification.id},
            )


async def test_reminder_count_limited_to_two(session: AsyncSession) -> None:
    notification = await _notification(session)
    notification.reminder_count = 3
    with pytest.raises(IntegrityError, match="reminder_count_range"):
        async with session.begin_nested():
            await session.flush()


async def test_reply_token_is_unique(session: AsyncSession) -> None:
    first = await _notification(session)
    duplicate = Notification(
        project_id=first.project_id,
        corpus_id=first.corpus_id,
        contractor_id=first.contractor_id,
        sarex_link=first.sarex_link,
        reply_token=first.reply_token,
        initiator_id=first.initiator_id,
        sent_at=first.sent_at,
        deadline_at=first.deadline_at,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError, match="uq_notifications_reply_token"):
        async with session.begin_nested():
            await session.flush()


async def test_corpus_names_unique_within_project(session: AsyncSession) -> None:
    project = Project(name="П", project_manager_email="pm@example.ru")
    session.add_all(
        [Corpus(project=project, name="Корпус 1"), Corpus(project=project, name="Корпус 1")]
    )
    with pytest.raises(IntegrityError, match="uq_corpuses_project_name"):
        async with session.begin_nested():
            await session.flush()


async def test_calendar_loaded_from_holidays_table(session: AsyncSession) -> None:
    session.add_all(
        [
            Holiday(date=date(2026, 11, 4), is_workday=False),
            Holiday(date=date(2026, 10, 31), is_workday=True),
            Holiday(date=date(2027, 1, 1), is_workday=False),
        ]
    )
    await session.flush()

    calendar = await load_calendar(session, date(2026, 10, 1), date(2026, 12, 31))

    assert calendar == {date(2026, 11, 4): False, date(2026, 10, 31): True}
    assert add_workdays(date(2026, 11, 2), 3, calendar) == date(2026, 11, 6)


async def test_deleting_project_link_keeps_contractor(session: AsyncSession) -> None:
    notification = await _notification(session)
    await session.execute(
        text("DELETE FROM project_contractors WHERE contractor_id = :id"),
        {"id": notification.contractor_id},
    )
    assert await session.scalar(select(func.count()).select_from(Contractor)) == 1

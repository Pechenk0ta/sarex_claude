"""Deadline chosen by the coordinator and manual status changes (TZ 4.1, 7.1, 7.3)."""

import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import (
    Channel,
    EventType,
    Holiday,
    Notification,
    NotificationEvent,
    NotificationStatus,
    Project,
    User,
)
from app.services.board import Display, Filters, build_board
from app.services.errors import ValidationError
from app.services.notifications import change_deadline, create_mailing, set_status
from app.services.workdays import add_workdays, local_date
from tests.integration.factories import project_with_contractors
from tests.integration.web_helpers import csrf, login

SETTINGS = Settings(
    _env_file=None,
    mail_address="rd@company.ru",
    secret_key="k" * 32,
    app_base_url="https://rd.example.ru",
)
# Fri 11.09.2026 10:00 Moscow time.
NOW = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)
LINK = "https://sarex.example.ru/project/sd-3/docs/KZH1-rev2"


async def _mailing(
    session: AsyncSession, deadline: date | None = None, contractors: int = 1
) -> tuple[list[Notification], User]:
    project, corpus, people, user = await project_with_contractors(session, contractors)
    result = await create_mailing(
        session,
        SETTINGS,
        initiator=user,
        project_id=project.id,
        corpus_id=corpus.id,
        sarex_link=LINK,
        message=None,
        contractor_ids=[c.id for c in people],
        deadline=deadline,
        now=NOW,
    )
    return result.notifications, user


async def _events(session: AsyncSession, notification: Notification) -> list[NotificationEvent]:
    return list(
        await session.scalars(
            select(NotificationEvent)
            .where(NotificationEvent.notification_id == notification.id)
            .order_by(NotificationEvent.created_at, NotificationEvent.type)
        )
    )


# --- deadline chosen when sending -----------------------------------------------------------


async def test_default_deadline_is_ten_workdays(session: AsyncSession) -> None:
    [notification], _ = await _mailing(session)
    assert notification.deadline_at == datetime(2026, 9, 25, 15, 0, tzinfo=UTC)  # 18:00 MSK


async def test_coordinator_sets_own_deadline(session: AsyncSession) -> None:
    [notification], _ = await _mailing(session, deadline=date(2026, 9, 18))

    assert notification.deadline_at == datetime(2026, 9, 18, 15, 0, tzinfo=UTC)
    [sent] = await _events(session, notification)
    assert "до 18.09.2026" in sent.payload["subject"]
    assert "до 18.09.2026" in sent.raw_content


@pytest.mark.parametrize(
    ("deadline", "error"),
    [
        (date(2026, 9, 11), "позже сегодняшнего дня"),
        (date(2026, 9, 10), "позже сегодняшнего дня"),
        (date(2026, 9, 19), "выходной"),  # Saturday
        (date(2027, 9, 20), "не дальше чем через год"),
    ],
)
async def test_invalid_deadline_is_explained(
    session: AsyncSession, deadline: date, error: str
) -> None:
    with pytest.raises(ValidationError, match=error):
        await _mailing(session, deadline=deadline)


async def test_holiday_cannot_be_the_deadline(session: AsyncSession) -> None:
    session.add(Holiday(date=date(2026, 9, 17), is_workday=False))
    await session.flush()
    with pytest.raises(ValidationError, match="выходной"):
        await _mailing(session, deadline=date(2026, 9, 17))


async def test_short_deadline_is_soon_on_the_board(session: AsyncSession) -> None:
    [notification], _ = await _mailing(session, deadline=date(2026, 9, 21))
    project = await session.get_one(Project, notification.project_id)
    board = await build_board(session, SETTINGS, project, date(2026, 9, 14), Filters())

    [item] = next(iter(board.cells.values())).items
    assert item.display is Display.SOON  # 5 working days left, not 9 as with the default
    assert item.term == 6


# --- manual status ---------------------------------------------------------------------------


async def test_manual_acknowledgement(session: AsyncSession) -> None:
    [notification], user = await _mailing(session)
    notification.needs_manual_review = True

    letters = await set_status(
        session,
        SETTINGS,
        notification,
        NotificationStatus.ACKNOWLEDGED,
        user=user,
        comment="Подтвердил по телефону",
        now=NOW + timedelta(days=1),
    )

    assert letters == []
    assert notification.status is NotificationStatus.ACKNOWLEDGED
    assert notification.acknowledged_at == NOW + timedelta(days=1)
    assert notification.needs_manual_review is False
    event = (await _events(session, notification))[-1]
    assert event.type is EventType.STATUS_CHANGED
    assert "«Ожидает ответа» → «Ознакомлен»" in event.raw_content
    assert "Подтвердил по телефону" in event.raw_content
    assert event.payload["user_name"] == "Смирнова Анна"
    assert event.payload["new_status"] == "acknowledged"
    assert "to" not in event.payload  # "to" is shown in the card as a mail recipient


async def test_same_status_or_escalated_is_refused(session: AsyncSession) -> None:
    [notification], user = await _mailing(session)

    with pytest.raises(ValidationError, match="Статус уже «Ожидает ответа»"):
        await set_status(session, SETTINGS, notification, NotificationStatus.SENT, user=user)
    with pytest.raises(ValidationError, match="нельзя выставить вручную"):
        await set_status(session, SETTINGS, notification, NotificationStatus.ESCALATED, user=user)


async def test_rejection_sends_one_letter_to_initiator_and_pm(session: AsyncSession) -> None:
    [notification], user = await _mailing(session)
    session.add(
        NotificationEvent(
            notification_id=notification.id,
            type=EventType.REPLY_QUESTION,
            channel=Channel.EMAIL,
            raw_content="Не принимаем: нет листа 14.",
            created_at=NOW + timedelta(hours=2),
        )
    )

    letters = await set_status(
        session, SETTINGS, notification, NotificationStatus.REJECTED, user=user
    )

    assert notification.status is NotificationStatus.REJECTED
    assert notification.rejected_at is not None
    [letter] = [e for e in await _events(session, notification) if e.id in letters]
    assert letter.type is EventType.REJECTION_NOTIFIED
    assert letter.payload["to"] == "coord@example.ru, pm@company.ru"
    assert letter.payload["delivery"] == "pending"
    assert letter.payload["subject"].startswith("РД не принята")
    assert "Не принимаем: нет листа 14." in letter.payload["text"]
    assert f"https://rd.example.ru/notifications/{notification.id}" in letter.payload["text"]

    await set_status(session, SETTINGS, notification, NotificationStatus.SENT, user=user)
    again = await set_status(
        session, SETTINGS, notification, NotificationStatus.REJECTED, user=user
    )
    assert again == []
    assert notification.rejected_at is not None
    types = [e.type for e in await _events(session, notification)]
    assert types.count(EventType.REJECTION_NOTIFIED) == 1


# --- manual deadline change ------------------------------------------------------------------


async def test_extending_deadline_of_escalated_notification(session: AsyncSession) -> None:
    [notification], user = await _mailing(session)
    notification.status = NotificationStatus.ESCALATED

    await change_deadline(
        session,
        SETTINGS,
        notification,
        date(2026, 10, 2),
        user=user,
        now=datetime(2026, 9, 28, 7, tzinfo=UTC),
    )

    assert notification.deadline_at == datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
    assert notification.status is NotificationStatus.SENT
    event = (await _events(session, notification))[-1]
    assert event.type is EventType.DEADLINE_CHANGED
    assert "25.09.2026 → 02.10.2026" in event.raw_content
    assert "Эскалировано РП" in event.raw_content
    assert event.payload == {
        "old_deadline": "2026-09-25",
        "new_deadline": "2026-10-02",
        "user_id": str(user.id),
        "user_name": "Смирнова Анна",
    }


async def test_deadline_of_answered_notification_is_not_changed(session: AsyncSession) -> None:
    [notification], user = await _mailing(session)
    await set_status(session, SETTINGS, notification, NotificationStatus.ACKNOWLEDGED, user=user)

    with pytest.raises(ValidationError, match="Ответ уже получен"):
        await change_deadline(
            session, SETTINGS, notification, date(2026, 10, 2), user=user, now=NOW
        )


# --- web: board, card and send form ----------------------------------------------------------


def _workday_ahead(days: int) -> date:
    """A working day `days` working days from today (the test database has no holidays)."""
    today = local_date(datetime.now(UTC), get_settings().app_timezone)
    return add_workdays(today, days, {})


async def _sent_by_web(
    client: httpx.AsyncClient, session: AsyncSession, contractors: int = 2
) -> list[Notification]:
    project, corpus, people, _ = await project_with_contractors(session, contractors)
    await session.commit()
    await login(client, "coord@example.ru", "coord-password-1")
    token = await csrf(client, f"/send?project_id={project.id}")
    response = await client.post(
        "/send",
        data={
            "csrf_token": token,
            "project_id": str(project.id),
            "corpus_id": str(corpus.id),
            "sarex_link": LINK,
            "contractor_ids": [str(c.id) for c in people],
            "deadline": _workday_ahead(3).isoformat(),
        },
    )
    assert response.status_code == 303
    return list(await session.scalars(select(Notification).order_by(Notification.sent_at)))


async def test_send_form_uses_chosen_deadline(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    notifications = await _sent_by_web(client, session)

    expected = _workday_ahead(3)
    assert {local_date(n.deadline_at, get_settings().app_timezone) for n in notifications} == {
        expected
    }
    page = await client.get(f"/send?project_id={notifications[0].project_id}")
    assert 'name="deadline" type="date"' in page.text


async def test_send_form_explains_weekend_deadline(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    project, corpus, people, _ = await project_with_contractors(session)
    await session.commit()
    await login(client, "coord@example.ru", "coord-password-1")
    today = local_date(datetime.now(UTC), get_settings().app_timezone)
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    token = await csrf(client, f"/send?project_id={project.id}")
    response = await client.post(
        "/send",
        data={
            "csrf_token": token,
            "project_id": str(project.id),
            "corpus_id": str(corpus.id),
            "sarex_link": LINK,
            "contractor_ids": [str(people[0].id)],
            "deadline": saturday.isoformat(),
        },
    )
    assert response.status_code == 400
    assert "Срок выпадает на выходной день" in response.text
    assert f'value="{saturday.isoformat()}"' in response.text
    assert await session.scalar(select(Notification.id)) is None


async def test_status_changed_from_the_board(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    first, second = await _sent_by_web(client, session)
    delivered.clear()
    board = await client.get(f"/?project_id={first.project_id}")
    assert f'action="/notifications/{first.id}/status"' in board.text
    assert "Изменить статус…" in board.text

    back = f"/?project_id={first.project_id}&open=x"
    token = await csrf(client, "/")
    response = await client.post(
        f"/notifications/{first.id}/status",
        data={"csrf_token": token, "status": "acknowledged", "back": back},
    )
    assert response.status_code == 303
    assert response.headers["location"] == back
    response = await client.post(
        f"/notifications/{second.id}/status",
        data={"csrf_token": token, "status": "rejected", "back": back},
    )
    await session.refresh(first)
    await session.refresh(second)
    assert first.status is NotificationStatus.ACKNOWLEDGED
    assert second.status is NotificationStatus.REJECTED
    assert len(delivered) == 1  # the rejection letter goes out right after the commit
    page = await client.get(response.headers["location"])
    assert "Письмо о непринятии уходит инициатору и РП." in page.text


async def test_status_form_refuses_foreign_redirect_and_unknown_status(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    [notification, _] = await _sent_by_web(client, session)
    notification_id = notification.id  # the handler's rollback expires the shared session
    token = await csrf(client, "/")

    response = await client.post(
        f"/notifications/{notification_id}/status",
        data={"csrf_token": token, "status": "escalated", "back": "//evil.example.com/"},
    )

    assert response.headers["location"] == f"/notifications/{notification_id}"
    page = await client.get(response.headers["location"])
    assert "Такой статус нельзя выставить вручную." in page.text
    no_csrf = await client.post(
        f"/notifications/{notification_id}/status", data={"status": "acknowledged"}
    )
    assert no_csrf.status_code == 403


async def test_card_changes_status_and_deadline(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    [notification, _] = await _sent_by_web(client, session)
    card = await client.get(f"/notifications/{notification.id}")
    assert "Решение координатора" in card.text
    assert 'name="deadline"' in card.text

    new_day = _workday_ahead(8)
    token = await csrf(client, f"/notifications/{notification.id}")
    response = await client.post(
        f"/notifications/{notification.id}/deadline",
        data={"csrf_token": token, "deadline": new_day.isoformat()},
    )
    page = await client.get(response.headers["location"])
    assert f"Новый срок ответа: {new_day:%d.%m.%Y}." in page.text
    assert "Срок ответа изменён" in page.text

    await client.post(
        f"/notifications/{notification.id}/status",
        data={"csrf_token": token, "status": "has_questions", "comment": "Звонил, есть вопрос"},
    )
    page = await client.get(f"/notifications/{notification.id}")
    assert "Статус изменён вручную" in page.text
    assert "Звонил, есть вопрос" in page.text
    await session.refresh(notification)
    assert notification.status is NotificationStatus.HAS_QUESTIONS

import re
import uuid
from collections.abc import Sequence

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import EventType, Notification, NotificationStatus
from app.services.ack_tokens import make_ack_token
from app.web.mail_deps import get_deliverer
from tests.integration.factories import project_with_contractors
from tests.integration.web_helpers import csrf, login

LINK = "https://sarex.example.ru/project/sd-3/docs/OV-rev1"


@pytest.fixture
def delivered(client: httpx.AsyncClient) -> list[uuid.UUID]:
    """Replaces real SMTP delivery: records which letters the request queued for sending."""
    calls: list[uuid.UUID] = []

    async def fake(event_ids: Sequence[uuid.UUID]) -> None:
        calls.extend(event_ids)

    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_deliverer] = lambda: fake
    return calls


async def test_coordinator_sends_mailing(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    project, corpus, people, _ = await project_with_contractors(session)
    await session.commit()
    await login(client, "coord@example.ru", "coord-password-1")

    page = await client.get(f"/send?project_id={project.id}")
    assert page.status_code == 200
    for c in people:
        assert c.name in page.text

    token = await csrf(client, f"/send?project_id={project.id}")
    response = await client.post(
        "/send",
        data={
            "csrf_token": token,
            "project_id": str(project.id),
            "corpus_id": str(corpus.id),
            "sarex_link": LINK,
            "message": "Изменена трасса кабеля",
            "contractor_ids": [str(people[0].id), str(people[2].id)],
        },
    )
    assert response.status_code == 303
    notifications = list(await session.scalars(select(Notification)))
    assert {n.contractor_id for n in notifications} == {people[0].id, people[2].id}
    assert len(delivered) == 2

    follow = await client.get(response.headers["location"])
    assert "Отправлено уведомлений: 2" in follow.text


async def test_invalid_form_is_shown_again_with_error(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    project, corpus, people, _ = await project_with_contractors(session)
    await session.commit()
    await login(client, "coord@example.ru", "coord-password-1")
    token = await csrf(client, f"/send?project_id={project.id}")

    response = await client.post(
        "/send",
        data={
            "csrf_token": token,
            "project_id": str(project.id),
            "corpus_id": str(corpus.id),
            "sarex_link": "не ссылка",
            "message": "Мой текст",
            "contractor_ids": [str(people[0].id)],
        },
    )
    assert response.status_code == 400
    assert "с https://" in response.text
    assert "Мой текст" in response.text  # what the user typed is kept
    assert delivered == []


async def test_already_sent_endpoint(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    project, corpus, people, _ = await project_with_contractors(session)
    await session.commit()
    await login(client, "coord@example.ru", "coord-password-1")
    token = await csrf(client, f"/send?project_id={project.id}")
    await client.post(
        "/send",
        data={
            "csrf_token": token,
            "project_id": str(project.id),
            "corpus_id": str(corpus.id),
            "sarex_link": LINK,
            "contractor_ids": [str(people[1].id)],
        },
    )
    response = await client.get(
        "/send/already-sent",
        params={"project_id": str(project.id), "corpus_id": str(corpus.id), "sarex_link": LINK},
    )
    assert response.json() == {"already_sent": [str(people[1].id)]}


async def test_ack_link_shows_page_and_confirms_only_on_post(
    client: httpx.AsyncClient, session: AsyncSession, delivered: list[uuid.UUID]
) -> None:
    project, corpus, people, _ = await project_with_contractors(session, 1)
    await session.commit()
    await login(client, "coord@example.ru", "coord-password-1")
    token = await csrf(client, f"/send?project_id={project.id}")
    await client.post(
        "/send",
        data={
            "csrf_token": token,
            "project_id": str(project.id),
            "corpus_id": str(corpus.id),
            "sarex_link": LINK,
            "contractor_ids": [str(people[0].id)],
        },
    )
    notification = await session.scalar(select(Notification))
    assert notification is not None
    ack = make_ack_token(get_settings(), notification.id)
    contractor_browser = httpx.AsyncClient(transport=client._transport, base_url="http://test")

    page = await contractor_browser.get(f"/ack/{ack}")
    assert page.status_code == 200
    assert "Подтвердите ознакомление" in page.text
    await session.refresh(notification)
    assert notification.status is NotificationStatus.SENT  # a GET (link scanner) changes nothing

    done = await contractor_browser.post(f"/ack/{ack}")
    assert "Спасибо, ознакомление подтверждено" in done.text
    again = await contractor_browser.post(f"/ack/{ack}")
    assert "Ознакомление уже подтверждено" in again.text
    await session.refresh(notification, ["status", "events"])
    assert notification.status is NotificationStatus.ACKNOWLEDGED
    assert [e.type for e in notification.events].count(EventType.REPLY_ACK) == 1


async def test_bad_ack_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/ack/not-a-token")
    assert response.status_code == 404
    assert re.search("недействительна", response.text)

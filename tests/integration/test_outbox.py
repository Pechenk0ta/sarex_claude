"""Letter delivery. These tests commit for real (the outbox opens its own sessions),
so each one cleans the tables afterwards."""

import asyncio
import socket
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from typing import Any

import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models import NotificationEvent
from app.services.mail.outbox import deliver_pending
from app.services.mail.sender import MailSendError, SmtpSender
from app.services.notifications import create_mailing
from tests.integration.factories import project_with_contractors

LINK = "https://sarex.example.ru/project/sd-3/docs/VK-rev1"


@pytest.fixture
async def sessions(migrated_database: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE notification_events, notifications, project_contractors, corpuses, "
                "contractors, projects, users, holidays CASCADE"
            )
        )
    await engine.dispose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Inbox:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        self.messages.append(message_from_bytes(envelope.content))
        return "250 OK"


@pytest.fixture
def smtp_server() -> Iterator[tuple[_Inbox, int]]:
    inbox = _Inbox()
    port = _free_port()
    controller = Controller(inbox, hostname="127.0.0.1", port=port)
    controller.start()
    yield inbox, port
    controller.stop()


async def _queue_letters(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, count: int
) -> list[NotificationEvent]:
    async with sessions() as session, session.begin():
        project, corpus, people, user = await project_with_contractors(session, count)
        result = await create_mailing(
            session,
            settings,
            initiator=user,
            project_id=project.id,
            corpus_id=corpus.id,
            sarex_link=LINK,
            message="Проверьте листы 3–5",
            contractor_ids=[c.id for c in people],
            now=datetime(2026, 9, 18, 7, tzinfo=UTC),
        )
        return [n.events[0] for n in result.notifications]


async def _payloads(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        return [e.payload for e in await session.scalars(select(NotificationEvent))]


async def test_letters_are_delivered_over_smtp(
    sessions: async_sessionmaker[AsyncSession], smtp_server: tuple[_Inbox, int]
) -> None:
    inbox, port = smtp_server
    settings = Settings(
        _env_file=None,
        mail_address="rd@company.ru",
        smtp_host="127.0.0.1",
        smtp_port=port,
        secret_key="k" * 32,
    )
    events = await _queue_letters(sessions, settings, 2)

    sent = await deliver_pending(sessions, settings, SmtpSender(settings))

    assert sent == 2
    assert sorted(m["To"] for m in inbox.messages) == ["p0@example.ru", "p1@example.ru"]
    reply_tos = {m["Reply-To"] for m in inbox.messages}
    assert reply_tos == {e.payload["reply_to"] for e in events}
    body = inbox.messages[0].get_payload()[0].get_payload(decode=True).decode()
    assert "Проверьте листы 3–5" in body
    assert all(p["delivery"] == "sent" for p in await _payloads(sessions))
    assert await deliver_pending(sessions, settings, SmtpSender(settings)) == 0  # nothing twice


class _Failing:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, message: EmailMessage) -> None:
        self.calls += 1
        raise MailSendError("connection refused")


async def test_failed_letters_are_retried_then_marked_failed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, mail_address="rd@company.ru", mail_max_attempts=2)
    events = await _queue_letters(sessions, settings, 3)
    sender = _Failing()

    # Inline attempt after the form: each letter tried once, retries left to the worker.
    await deliver_pending(sessions, settings, sender, [e.id for e in events])
    assert sender.calls == 3
    assert {p["delivery"] for p in await _payloads(sessions)} == {"pending"}

    # Worker run while the server is down: stops after the first failure.
    await deliver_pending(sessions, settings, sender)
    payloads = await _payloads(sessions)
    assert sender.calls == 4
    assert sorted(p["delivery"] for p in payloads) == ["failed", "pending", "pending"]
    assert all(p["last_error"] == "connection refused" for p in payloads)


class _Slow:
    def __init__(self) -> None:
        self.recipients: list[str] = []

    async def send(self, message: EmailMessage) -> None:
        await asyncio.sleep(0.05)
        self.recipients.append(str(message["To"]))


async def test_parallel_runs_do_not_send_twice(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, mail_address="rd@company.ru")
    await _queue_letters(sessions, settings, 4)
    sender = _Slow()

    await asyncio.gather(
        deliver_pending(sessions, settings, sender), deliver_pending(sessions, settings, sender)
    )

    assert sorted(sender.recipients) == [f"p{i}@example.ru" for i in range(4)]

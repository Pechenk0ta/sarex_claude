from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Contractor, Corpus, EventType, Holiday, Notification, Project
from app.services.errors import ValidationError
from app.services.notifications import acknowledge_by_button, create_mailing
from tests.integration.factories import project_with_contractors

SETTINGS = Settings(_env_file=None, mail_address="rd@company.ru", secret_key="k" * 32)
# Fri 11.09.2026 10:00 Moscow time.
NOW = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)
LINK = "https://sarex.example.ru/project/sd-3/docs/KZH1-rev2"


async def test_one_notification_and_queued_letter_per_contractor(session: AsyncSession) -> None:
    project, corpus, people, user = await project_with_contractors(session)

    result = await create_mailing(
        session,
        SETTINGS,
        initiator=user,
        project_id=project.id,
        corpus_id=corpus.id,
        sarex_link=f"  {LINK} ",
        message="Листы 12–14",
        contractor_ids=[c.id for c in people],
        now=NOW,
    )

    assert len(result.notifications) == 3
    tokens = {n.reply_token for n in result.notifications}
    assert len(tokens) == 3
    for n in result.notifications:
        assert n.sarex_link == LINK
        assert n.message == "Листы 12–14"
        # 10 working days after Fri 11.09 -> Fri 25.09, 18:00 Moscow = 15:00 UTC.
        assert n.deadline_at == datetime(2026, 9, 25, 15, 0, tzinfo=UTC)
        [event] = n.events
        assert event.type is EventType.SENT
        assert event.payload["delivery"] == "pending"
        assert event.payload["reply_to"] == f"rd+{n.reply_token}@company.ru"
        assert "Листы 12–14" in event.raw_content


async def test_holiday_moves_deadline(session: AsyncSession) -> None:
    project, corpus, people, user = await project_with_contractors(session, 1)
    session.add(Holiday(date=date(2026, 9, 21), is_workday=False))
    await session.flush()
    result = await create_mailing(
        session,
        SETTINGS,
        initiator=user,
        project_id=project.id,
        corpus_id=corpus.id,
        sarex_link=LINK,
        message=None,
        contractor_ids=[people[0].id],
        now=NOW,
    )
    assert result.notifications[0].deadline_at == datetime(2026, 9, 28, 15, 0, tzinfo=UTC)


async def test_excluded_contractors_get_nothing(session: AsyncSession) -> None:
    project, corpus, people, user = await project_with_contractors(session)
    result = await create_mailing(
        session,
        SETTINGS,
        initiator=user,
        project_id=project.id,
        corpus_id=corpus.id,
        sarex_link=LINK,
        message=None,
        contractor_ids=[people[0].id],
        now=NOW,
    )
    assert [n.contractor_id for n in result.notifications] == [people[0].id]


async def test_resend_goes_only_to_those_who_did_not_get_it(session: AsyncSession) -> None:
    project, corpus, people, user = await project_with_contractors(session)
    await create_mailing(
        session,
        SETTINGS,
        initiator=user,
        project_id=project.id,
        corpus_id=corpus.id,
        sarex_link=LINK,
        message=None,
        contractor_ids=[people[0].id, people[1].id],
        now=NOW,
    )
    again = await create_mailing(
        session,
        SETTINGS,
        initiator=user,
        project_id=project.id,
        corpus_id=corpus.id,
        sarex_link=LINK,
        message=None,
        contractor_ids=[c.id for c in people],
        now=NOW,
    )
    assert [n.contractor_id for n in again.notifications] == [people[2].id]
    assert {c.id for c in again.skipped_already_sent} == {people[0].id, people[1].id}
    assert await session.scalar(select(func.count()).select_from(Notification)) == 3


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("inactive_project", "активный проект"),
        ("foreign_corpus", "корпус этого проекта"),
        ("bad_link", "с https://"),
        ("stranger", "не назначенный на этот корпус"),
        ("nobody", "Некому отправлять"),
    ],
)
async def test_invalid_mailings_are_explained(
    session: AsyncSession, change: str, message: str
) -> None:
    project, corpus, people, user = await project_with_contractors(session)
    corpus_id, link, ids = corpus.id, LINK, [c.id for c in people]
    if change == "inactive_project":
        project.is_active = False
    elif change == "foreign_corpus":
        other = Corpus(project=Project(name="Другой", project_manager_email="x@x.ru"), name="К")
        session.add(other)
        await session.flush()
        corpus_id = other.id
    elif change == "bad_link":
        link = "sarex/doc"
    elif change == "stranger":
        stranger = Contractor(name="ООО «Чужой»", email="s@example.ru")
        session.add(stranger)
        await session.flush()
        ids.append(stranger.id)
    elif change == "nobody":
        ids = []
    with pytest.raises(ValidationError, match=message):
        await create_mailing(
            session,
            SETTINGS,
            initiator=user,
            project_id=project.id,
            corpus_id=corpus_id,
            sarex_link=link,
            message=None,
            contractor_ids=ids,
            now=NOW,
        )


async def test_acknowledge_by_button_is_idempotent(session: AsyncSession) -> None:
    project, corpus, people, user = await project_with_contractors(session, 1)
    [notification] = (
        await create_mailing(
            session,
            SETTINGS,
            initiator=user,
            project_id=project.id,
            corpus_id=corpus.id,
            sarex_link=LINK,
            message=None,
            contractor_ids=[people[0].id],
            now=NOW,
        )
    ).notifications
    assert await acknowledge_by_button(session, notification) is True
    assert await acknowledge_by_button(session, notification) is False
    await session.refresh(notification, ["events"])
    assert [e.type for e in notification.events] == [EventType.SENT, EventType.REPLY_ACK]
    assert notification.acknowledged_at is not None

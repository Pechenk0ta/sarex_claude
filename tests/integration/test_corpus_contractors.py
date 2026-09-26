"""Contractors are assigned to corpuses (TZ 3.3): recipients, directory screen, board."""

from datetime import date

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Contractor, Corpus, CorpusContractor, Project, User, UserRole
from app.services import directory
from app.services.board import Filters, build_board
from app.services.errors import ValidationError
from app.services.notifications import create_mailing, recipients
from app.services.users import create_user
from tests.integration.web_helpers import login, post

SETTINGS = Settings(_env_file=None, mail_address="rd@company.ru", secret_key="k" * 32)
LINK = "https://sarex.example.ru/project/sd-3/docs/AR-rev3"


async def _two_corpuses(
    session: AsyncSession,
) -> tuple[Project, Corpus, Corpus, Contractor, Contractor, User]:
    project = Project(name="ЖК «Тест»", project_manager_email="pm@company.ru")
    first = Corpus(project=project, name="Корпус 1")
    second = Corpus(project=project, name="Корпус 2")
    frame = Contractor(name="ООО «Каркас»", email="frame@example.ru")
    lift = Contractor(name="ООО «Лифт»", email="lift@example.ru")
    user = await create_user(
        session, "admin@example.ru", "Кузнецов Павел", UserRole.ADMIN, "admin-password-1"
    )
    session.add_all([project, first, second, frame, lift])
    await session.flush()
    await directory.assign_contractor(session, project, frame.id, None)
    await directory.assign_contractor(session, project, lift.id, second.id)
    return project, first, second, frame, lift, user


async def test_recipients_are_contractors_of_the_corpus(session: AsyncSession) -> None:
    _, first, second, frame, lift, _ = await _two_corpuses(session)

    assert [r.contractor for r in await recipients(session, first.id, LINK)] == [frame]
    assert [r.contractor for r in await recipients(session, second.id, LINK)] == [frame, lift]
    assert await recipients(session, None, LINK) == []


async def test_mailing_rejects_contractor_of_another_corpus(session: AsyncSession) -> None:
    project, first, _, _, lift, user = await _two_corpuses(session)

    with pytest.raises(ValidationError, match="не назначенный на этот корпус"):
        await create_mailing(
            session,
            SETTINGS,
            initiator=user,
            project_id=project.id,
            corpus_id=first.id,
            sarex_link=LINK,
            message=None,
            contractor_ids=[lift.id],
        )


async def test_assign_to_all_skips_inactive_corpuses_and_is_idempotent(
    session: AsyncSession,
) -> None:
    project, first, second, _, _, _ = await _two_corpuses(session)
    parking = Corpus(project=project, name="Паркинг", is_active=False)
    newcomer = Contractor(name="ООО «Новый»", email="new@example.ru")
    session.add_all([parking, newcomer])
    await session.flush()

    assert await directory.assign_contractor(session, project, newcomer.id, None) == 2
    assert await directory.assign_contractor(session, project, newcomer.id, None) == 0
    corpuses = set(
        await session.scalars(
            select(CorpusContractor.corpus_id).where(CorpusContractor.contractor_id == newcomer.id)
        )
    )
    assert corpuses == {first.id, second.id}


async def test_assign_to_corpus_of_another_project_is_refused(session: AsyncSession) -> None:
    project, _, _, frame, _, _ = await _two_corpuses(session)
    other = Project(name="ЖК «Другой»", project_manager_email="pm@company.ru")
    foreign = Corpus(project=other, name="Корпус 9")
    session.add_all([other, foreign])
    await session.flush()

    with pytest.raises(ValidationError, match="Выберите корпус этого проекта"):
        await directory.assign_contractor(session, project, frame.id, foreign.id)


async def test_directory_shows_assignments(session: AsyncSession) -> None:
    project, _, _, frame, lift, _ = await _two_corpuses(session)

    rows = {r.contractor.name: r.assignments for r in await directory.list_contractors(session)}
    assert rows == {
        "ООО «Каркас»": ["ЖК «Тест»: Корпус 1, Корпус 2"],
        "ООО «Лифт»": ["ЖК «Тест»: Корпус 2"],
    }
    listed = (await directory.list_projects(session))[0]
    assert listed.contractor_count == 2
    details = await directory.get_project(session, project.id)
    assert details is not None
    assert {r.corpus.name: r.contractors for r in details.corpuses} == {
        "Корпус 1": [frame],
        "Корпус 2": [frame, lift],
    }


async def test_board_counts_as_not_received_only_contractors_of_that_corpus(
    session: AsyncSession,
) -> None:
    project, first, second, frame, lift, user = await _two_corpuses(session)
    for corpus in (first, second):
        await create_mailing(
            session,
            SETTINGS,
            initiator=user,
            project_id=project.id,
            corpus_id=corpus.id,
            sarex_link=LINK,
            message=None,
            contractor_ids=[frame.id],
        )

    board = await build_board(session, SETTINGS, project, date(2026, 9, 26), Filters())

    assert board.cells[(first.id, LINK)].excluded == []
    assert board.cells[(second.id, LINK)].excluded == [lift]
    assert board.contractors == [frame, lift]


async def test_admin_assigns_and_unassigns_on_the_directory_screen(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    project, first, second, frame, lift, _ = await _two_corpuses(session)
    await session.commit()
    await login(client, "admin@example.ru", "admin-password-1")

    await post(
        client,
        f"/refs/projects/{project.id}/contractors",
        {"contractor_id": str(lift.id), "corpus_id": str(first.id)},
    )
    await post(
        client,
        f"/refs/projects/{project.id}/corpuses/{second.id}/contractors/{frame.id}/unassign",
        {},
    )
    page = await client.get(f"/refs/projects/{project.id}")

    assert "Подрядчики по корпусам" in page.text
    links = set(
        (
            await session.execute(
                select(CorpusContractor.corpus_id, CorpusContractor.contractor_id)
            )
        ).all()
    )
    assert links == {(first.id, frame.id), (first.id, lift.id), (second.id, lift.id)}


async def test_coordinator_cannot_assign(client: httpx.AsyncClient, session: AsyncSession) -> None:
    project, first, _, _, lift, _ = await _two_corpuses(session)
    await create_user(
        session, "coord@example.ru", "Смирнова Анна", UserRole.COORDINATOR, "coord-password-1"
    )
    await session.commit()
    await login(client, "coord@example.ru", "coord-password-1")

    response = await post(
        client,
        f"/refs/projects/{project.id}/contractors",
        {"contractor_id": str(lift.id), "corpus_id": str(first.id)},
    )

    assert response.status_code == 403
    count = await session.scalar(select(func.count()).select_from(CorpusContractor))
    assert count == 3


async def test_send_form_lists_contractors_of_chosen_corpus(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    project, first, second, _, _, _ = await _two_corpuses(session)
    await session.commit()
    await login(client, "admin@example.ru", "admin-password-1")

    no_corpus = await client.get(f"/send?project_id={project.id}")
    assert "ООО «Лифт»" not in no_corpus.text
    assert "Выберите корпус: получателями станут его подрядчики." in no_corpus.text

    page = await client.get(
        f"/send?project_id={project.id}&corpus_id={second.id}&sarex_link={LINK}&message=Лист+3"
    )
    assert "ООО «Лифт»" in page.text
    assert "ООО «Каркас»" in page.text
    assert LINK in page.text
    assert "Лист 3" in page.text
    first_page = await client.get(f"/send?project_id={project.id}&corpus_id={first.id}")
    assert "ООО «Лифт»" not in first_page.text

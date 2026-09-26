from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Corpus, Notification, NotificationStatus, Project, UserRole
from app.scripts.seed_demo import DEMO_PROJECT, seed
from app.services.board import Display, Filters, build_board, build_card
from app.services.users import create_user
from tests.integration.web_helpers import login

SETTINGS = Settings(_env_file=None)
TODAY = date(2026, 9, 26)


async def _demo(session: AsyncSession) -> Project:
    await seed(session)
    project = await session.scalar(select(Project).where(Project.name == DEMO_PROJECT))
    assert project is not None
    return project


async def test_board_counts_match_the_mockup(session: AsyncSession) -> None:
    project = await _demo(session)
    board = await build_board(session, SETTINGS, project, TODAY, Filters())

    assert board.total == 59
    assert dict(board.counts) == {
        Display.OK: 42,
        Display.WAITING: 8,
        Display.SOON: 3,
        Display.QUESTIONS: 3,
        Display.REJECTED: 1,
        Display.REVIEW: 1,
        Display.LATE: 1,
    }
    assert len(board.columns) == 5
    # Corpus 4 has no mailings but is active, so it is shown with empty cells.
    assert [c.name for c in board.corpuses][-1] == "Корпус 4 · паркинг"


async def test_cell_summary_and_excluded_contractor(session: AsyncSession) -> None:
    project = await _demo(session)
    board = await build_board(session, SETTINGS, project, TODAY, Filters())
    corpus1 = next(c for c in board.corpuses if c.name.startswith("Корпус 1"))
    vk = next(col for col in board.columns if col.title == "VK-rev1")
    cell = board.cells[(corpus1.id, vk.sarex_link)]

    assert (cell.acknowledged, cell.total) == (2, 4)
    assert cell.worst is Display.SOON
    assert cell.worst_count == 2
    assert [c.name for c in cell.excluded] == ["ООО «ФасадПро»"]


async def test_worst_status_in_cell_is_rejection(session: AsyncSession) -> None:
    project = await _demo(session)
    board = await build_board(session, SETTINGS, project, TODAY, Filters())
    corpus1 = next(c for c in board.corpuses if c.name.startswith("Корпус 1"))
    ov = next(col for col in board.columns if col.title == "OV-rev1")
    assert board.cells[(corpus1.id, ov.sarex_link)].worst is Display.REJECTED


async def test_filters(session: AsyncSession) -> None:
    project = await _demo(session)
    only_questions = await build_board(
        session, SETTINGS, project, TODAY, Filters(display=Display.QUESTIONS)
    )
    assert only_questions.total == 3
    corpus2 = await session.scalar(select(Corpus).where(Corpus.name.startswith("Корпус 2")))
    assert corpus2 is not None
    one_corpus = await build_board(session, SETTINGS, project, TODAY, Filters(corpus_id=corpus2.id))
    assert [c.id for c in one_corpus.corpuses] == [corpus2.id]
    assert one_corpus.total == 20  # 4 mailings × 5 contractors


async def test_waiting_turns_late_after_deadline(session: AsyncSession) -> None:
    project = await _demo(session)
    later = await build_board(session, SETTINGS, project, date(2026, 10, 20), Filters())
    assert later.counts[Display.WAITING] == 0
    assert later.counts[Display.LATE] == 1 + 8 + 3  # nothing answered, all overdue


async def test_card_contains_history_and_mailing_stats(session: AsyncSession) -> None:
    await _demo(session)
    rejected = await session.scalar(
        select(Notification).where(Notification.status == NotificationStatus.REJECTED)
    )
    assert rejected is not None
    card = await build_card(session, SETTINGS, rejected.id, TODAY)
    assert card is not None
    assert card.display is Display.REJECTED
    assert card.mailing_total == 5
    assert [e.type.value for e in card.events][-2:] == ["reply_rejection", "rejection_notified"]


# --- web ------------------------------------------------------------------------------------


async def _coordinator(session: AsyncSession) -> None:
    await create_user(
        session, "c@example.ru", "Смирнова Анна", UserRole.COORDINATOR, "password-123"
    )
    await session.commit()


async def test_board_page_and_card_page(client: httpx.AsyncClient, session: AsyncSession) -> None:
    project = await _demo(session)
    await _coordinator(session)
    await login(client, "c@example.ru", "password-123")

    page = await client.get(f"/?project_id={project.id}")
    assert page.status_code == 200
    assert DEMO_PROJECT in page.text
    assert "KZH1-rev2" in page.text
    assert "Ознакомлены" in page.text

    notification = await session.scalar(
        select(Notification).where(Notification.needs_manual_review)
    )
    assert notification is not None
    card = await client.get(f"/notifications/{notification.id}")
    assert card.status_code == 200
    assert "ИИ не смог уверенно классифицировать ответ" in card.text
    assert "По узлу 4 уточним позже" in card.text

    assert (
        await client.get("/notifications/00000000-0000-0000-0000-000000000000")
    ).status_code == 404


async def test_api_requires_login_and_returns_board(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    project = await _demo(session)
    await _coordinator(session)
    assert (await client.get(f"/api/dashboard?project_id={project.id}")).status_code == 401

    await login(client, "c@example.ru", "password-123")
    data = (await client.get(f"/api/dashboard?project_id={project.id}")).json()
    assert data["counts"]["ok"] == 42
    assert len(data["columns"]) == 5

    notification = await session.scalar(select(Notification).limit(1))
    assert notification is not None
    detail = (await client.get(f"/api/notifications/{notification.id}")).json()
    event_id = detail["events"][0]["id"]
    raw = (await client.get(f"/api/notifications/{notification.id}/events/{event_id}")).json()
    assert raw["raw_content"].startswith("Тема:")

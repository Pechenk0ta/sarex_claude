import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.main import create_app
from app.models import Contractor, Corpus, Holiday, Notification, Project, User, UserRole
from app.services import directory, users
from app.services.errors import ValidationError

ADMIN_PASSWORD = "admin-password-1"
COORD_PASSWORD = "coord-password-1"


@pytest.fixture
async def admin(session: AsyncSession) -> User:
    user = await users.create_user(
        session, "admin@example.ru", "Кузнецов Павел", UserRole.ADMIN, ADMIN_PASSWORD
    )
    await session.commit()  # in tests commit only releases a savepoint; see conftest
    return user


@pytest.fixture
async def coordinator(session: AsyncSession) -> User:
    user = await users.create_user(
        session, "coord@example.ru", "Смирнова Анна", UserRole.COORDINATOR, COORD_PASSWORD
    )
    await session.commit()
    return user


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _csrf(client: httpx.AsyncClient, path: str) -> str:
    page = await client.get(path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match, f"no CSRF token on {path}"
    return match.group(1)


async def _login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    token = await _csrf(client, "/login")
    return await client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token, "next": "/"}
    )


async def _post(client: httpx.AsyncClient, path: str, data: dict[str, str]) -> httpx.Response:
    token = await _csrf(client, "/refs/users")
    return await client.post(path, data={**data, "csrf_token": token})


# --- login ----------------------------------------------------------------------------------


async def test_pages_require_login(client: httpx.AsyncClient) -> None:
    response = await client.get("/refs/contractors")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/refs/contractors"


async def test_login_with_wrong_password_shows_error(
    client: httpx.AsyncClient, coordinator: User
) -> None:
    response = await _login(client, "coord@example.ru", "wrong-password")
    assert response.status_code == 400
    assert "Неверный email или пароль" in response.text


async def test_login_and_logout(client: httpx.AsyncClient, coordinator: User) -> None:
    response = await _login(client, "COORD@example.ru ", COORD_PASSWORD)
    assert response.status_code == 303
    assert (await client.get("/refs/projects")).status_code == 200

    token = await _csrf(client, "/refs/users")
    await client.post("/logout", data={"csrf_token": token})
    assert (await client.get("/refs/projects")).status_code == 303


async def test_login_does_not_redirect_to_other_sites(
    client: httpx.AsyncClient, coordinator: User
) -> None:
    token = await _csrf(client, "/login")
    response = await client.post(
        "/login",
        data={
            "email": "coord@example.ru",
            "password": COORD_PASSWORD,
            "csrf_token": token,
            "next": "//evil.example/steal",
        },
    )
    assert response.headers["location"] == "/"


async def test_inactive_user_cannot_log_in_and_is_logged_out(
    client: httpx.AsyncClient, session: AsyncSession, coordinator: User, admin: User
) -> None:
    await _login(client, "coord@example.ru", COORD_PASSWORD)
    await users.set_active(session, coordinator, False, acting=admin)

    assert (await client.get("/refs/projects")).status_code == 303
    assert (await _login(client, "coord@example.ru", COORD_PASSWORD)).status_code == 400


async def test_form_without_csrf_token_is_rejected(client: httpx.AsyncClient, admin: User) -> None:
    await _login(client, "admin@example.ru", ADMIN_PASSWORD)
    response = await client.post("/refs/contractors", data={"name": "ООО «X»", "email": "x@x.ru"})
    assert response.status_code == 403


# --- roles ----------------------------------------------------------------------------------


async def test_coordinator_reads_but_cannot_change(
    client: httpx.AsyncClient, session: AsyncSession, coordinator: User
) -> None:
    await directory.create_contractor(session, "ООО «СтройМонолит»", "pto@stroymonolit.ru")
    await _login(client, "coord@example.ru", COORD_PASSWORD)

    page = await client.get("/refs/contractors")
    assert page.status_code == 200
    assert "ООО «СтройМонолит»" in page.text
    assert "Добавить подрядчика" not in page.text

    response = await _post(client, "/refs/contractors", {"name": "ООО «Y»", "email": "y@y.ru"})
    assert response.status_code == 403
    assert await session.scalar(select(Contractor).where(Contractor.name == "ООО «Y»")) is None


# --- projects, corpuses, contractors --------------------------------------------------------


async def test_admin_creates_project_with_corpus_and_contractor(
    client: httpx.AsyncClient, session: AsyncSession, admin: User
) -> None:
    contractor = await directory.create_contractor(session, "ООО «АкваИнж»", "pto@akvainzh.ru")
    await session.commit()
    await _login(client, "admin@example.ru", ADMIN_PASSWORD)

    response = await _post(
        client,
        "/refs/projects",
        {"name": "ЖК «Речной квартал»", "project_manager_email": "PM@Company.ru"},
    )
    project = await session.scalar(select(Project).where(Project.name == "ЖК «Речной квартал»"))
    assert project is not None
    assert project.project_manager_email == "pm@company.ru"
    assert response.headers["location"] == f"/refs/projects/{project.id}"

    await _post(client, f"/refs/projects/{project.id}/corpuses", {"name": "Корпус 1"})
    await _post(
        client, f"/refs/projects/{project.id}/contractors", {"contractor_id": str(contractor.id)}
    )
    page = await client.get(f"/refs/projects/{project.id}")
    assert "Корпус 1" in page.text
    assert "Корпус добавлен." in page.text or "Подрядчик привязан" in page.text
    assert "ООО «АкваИнж»" in page.text


async def test_invalid_email_is_explained(client: httpx.AsyncClient, admin: User) -> None:
    await _login(client, "admin@example.ru", ADMIN_PASSWORD)
    response = await _post(
        client, "/refs/projects", {"name": "ЖК «Ошибка»", "project_manager_email": "не-почта"}
    )
    page = await client.get(response.headers["location"])
    assert "Проверьте адрес электронной почты." in page.text


async def test_duplicate_contractor_rejected(
    client: httpx.AsyncClient, session: AsyncSession, admin: User
) -> None:
    await directory.create_contractor(session, "ООО «ФасадПро»", "tender@fasadpro.ru")
    await session.commit()
    await _login(client, "admin@example.ru", ADMIN_PASSWORD)
    await _post(client, "/refs/contractors", {"name": "ооо «фасадпро»", "email": "new@x.ru"})
    page = await client.get("/refs/contractors")
    assert "Подрядчик с таким названием уже есть." in page.text


async def test_corpus_with_notifications_cannot_be_deleted(
    session: AsyncSession, admin: User
) -> None:
    project = await directory.create_project(session, "П", None, "pm@example.ru")
    corpus = await directory.add_corpus(session, project, "Корпус 1")
    contractor = await directory.create_contractor(session, "ООО «Т»", "t@example.ru")
    session.add(
        Notification(
            project_id=project.id,
            corpus_id=corpus.id,
            contractor_id=contractor.id,
            sarex_link="https://sarex.example.ru/x",
            reply_token="t1",
            initiator_id=admin.id,
            sent_at=datetime(2026, 9, 1, tzinfo=UTC),
            deadline_at=datetime(2026, 9, 15, tzinfo=UTC),
        )
    )
    await session.flush()

    with pytest.raises(ValidationError, match="только отключить"):
        await directory.delete_corpus(session, corpus)


async def test_empty_corpus_can_be_deleted(
    client: httpx.AsyncClient, session: AsyncSession, admin: User
) -> None:
    project = await directory.create_project(session, "П2", None, "pm@example.ru")
    corpus = await directory.add_corpus(session, project, "Корпус 9")
    await _login(client, "admin@example.ru", ADMIN_PASSWORD)
    await _post(client, f"/refs/projects/{project.id}/corpuses/{corpus.id}/delete", {})
    assert await session.get(Corpus, corpus.id) is None


# --- users ----------------------------------------------------------------------------------


async def test_new_user_gets_temporary_password_and_can_log_in(
    client: httpx.AsyncClient, admin: User
) -> None:
    await _login(client, "admin@example.ru", ADMIN_PASSWORD)
    await _post(
        client,
        "/refs/users",
        {"full_name": "Орлов Максим", "email": "m.orlov@example.ru", "role": "coordinator"},
    )
    page = await client.get("/refs/users")
    match = re.search(r'class="secret">([^<]+)<', page.text)
    assert match, "temporary password is shown once"
    assert "secret" not in (await client.get("/refs/users")).text  # not shown again

    await client.post("/logout", data={"csrf_token": await _csrf(client, "/refs/users")})
    response = await _login(client, "m.orlov@example.ru", match.group(1))
    assert response.status_code == 303


async def test_last_admin_cannot_be_disabled(session: AsyncSession, admin: User) -> None:
    other = await users.create_user(
        session, "admin2@example.ru", "Второй", UserRole.ADMIN, "password-123"
    )
    await users.set_active(session, other, False, acting=admin)
    with pytest.raises(ValidationError, match="собственную"):
        await users.set_active(session, admin, False, acting=admin)
    with pytest.raises(ValidationError, match="последнего администратора"):
        await users.set_active(session, admin, False, acting=other)


async def test_short_password_rejected(session: AsyncSession) -> None:
    with pytest.raises(ValidationError, match="не короче 10"):
        await users.create_user(session, "a@example.ru", "А", UserRole.COORDINATOR, "short")


# --- calendar -------------------------------------------------------------------------------


async def test_calendar_accepts_holidays_and_rejects_pointless_entries(
    client: httpx.AsyncClient, session: AsyncSession, admin: User
) -> None:
    await _login(client, "admin@example.ru", ADMIN_PASSWORD)
    await _post(client, "/refs/calendar", {"day": "2026-11-04", "is_workday": "false"})
    await _post(client, "/refs/calendar", {"day": "2026-11-07", "is_workday": "false"})

    page = await client.get("/refs/calendar?year=2026")
    assert "04.11.2026" in page.text
    assert "Суббота и воскресенье и так выходные" in page.text
    assert await session.get(Holiday, datetime(2026, 11, 7).date()) is None

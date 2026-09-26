"""Directories screen (mockup "Справочники"): everyone reads, only admins change."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import generate_password
from app.db import SessionDep
from app.models import Contractor, Project, User, UserRole
from app.services import directory, users
from app.services.errors import ValidationError
from app.web.deps import AdminUser, CurrentUser
from app.web.session import flash, verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/refs")
CSRF = [Depends(verify_csrf)]  # every form POST checks the CSRF token

FormStr = Annotated[str, Form()]
FormOptStr = Annotated[str | None, Form()]
FormBool = Annotated[bool, Form()]


async def _apply(
    request: Request,
    session: AsyncSession,
    action: Callable[[], Awaitable[object]],
    success: str,
    redirect_to: str,
) -> RedirectResponse:
    """Run a service call, commit on success, show the result as a flash message."""
    try:
        await action()
        await session.commit()
        flash(request, success)
    except ValidationError as error:
        await session.rollback()
        flash(request, error.message, "error")
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)


async def _project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден.")
    return project


@router.get("")
async def refs_root(user: CurrentUser) -> RedirectResponse:
    return RedirectResponse("/refs/projects", status_code=status.HTTP_303_SEE_OTHER)


# --- projects and corpuses ------------------------------------------------------------------


@router.get("/projects")
async def projects_page(request: Request, session: SessionDep, user: CurrentUser) -> Any:
    rows = await directory.list_projects(session)
    if rows:
        return RedirectResponse(f"/refs/projects/{rows[0].project.id}", status_code=303)
    return render(request, "refs/projects.html", tab="projects", rows=rows, details=None)


@router.get("/projects/new")
async def new_project_page(request: Request, session: SessionDep, user: AdminUser) -> Any:
    rows = await directory.list_projects(session)
    return render(request, "refs/projects.html", tab="projects", rows=rows, details=None, new=True)


@router.post("/projects", dependencies=CSRF)
async def create_project(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    name: FormStr,
    project_manager_email: FormStr,
    address: FormOptStr = None,
) -> RedirectResponse:
    created: list[Project] = []

    async def action() -> None:
        created.append(
            await directory.create_project(session, name, address, project_manager_email)
        )

    response = await _apply(request, session, action, "Проект добавлен.", "/refs/projects/new")
    if created:
        response.headers["location"] = f"/refs/projects/{created[0].id}"
    return response


@router.get("/projects/{project_id}")
async def project_page(
    request: Request, session: SessionDep, user: CurrentUser, project_id: uuid.UUID
) -> Any:
    details = await directory.get_project(session, project_id)
    if details is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден.")
    rows = await directory.list_projects(session)
    return render(request, "refs/projects.html", tab="projects", rows=rows, details=details)


@router.post("/projects/{project_id}", dependencies=CSRF)
async def update_project(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    project_id: uuid.UUID,
    name: FormStr,
    project_manager_email: FormStr,
    address: FormOptStr = None,
    is_active: FormBool = False,
) -> RedirectResponse:
    project = await _project(session, project_id)
    return await _apply(
        request,
        session,
        lambda: directory.update_project(
            session, project, name, address, project_manager_email, is_active
        ),
        "Изменения проекта сохранены.",
        f"/refs/projects/{project_id}",
    )


@router.post("/projects/{project_id}/corpuses", dependencies=CSRF)
async def add_corpus(
    request: Request, session: SessionDep, user: AdminUser, project_id: uuid.UUID, name: FormStr
) -> RedirectResponse:
    project = await _project(session, project_id)
    return await _apply(
        request,
        session,
        lambda: directory.add_corpus(session, project, name),
        "Корпус добавлен.",
        f"/refs/projects/{project_id}",
    )


@router.post("/projects/{project_id}/corpuses/{corpus_id}", dependencies=CSRF)
async def update_corpus(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    project_id: uuid.UUID,
    corpus_id: uuid.UUID,
    name: FormStr,
    is_active: FormBool = False,
) -> RedirectResponse:
    corpus = await directory.get_corpus(session, project_id, corpus_id)
    if corpus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Корпус не найден.")
    return await _apply(
        request,
        session,
        lambda: directory.update_corpus(session, corpus, name, is_active),
        "Корпус сохранён.",
        f"/refs/projects/{project_id}",
    )


@router.post("/projects/{project_id}/corpuses/{corpus_id}/delete", dependencies=CSRF)
async def delete_corpus(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    project_id: uuid.UUID,
    corpus_id: uuid.UUID,
) -> RedirectResponse:
    corpus = await directory.get_corpus(session, project_id, corpus_id)
    if corpus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Корпус не найден.")
    return await _apply(
        request,
        session,
        lambda: directory.delete_corpus(session, corpus),
        "Корпус удалён.",
        f"/refs/projects/{project_id}",
    )


@router.post("/projects/{project_id}/contractors", dependencies=CSRF)
async def link_contractor(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    project_id: uuid.UUID,
    contractor_id: FormStr,
) -> RedirectResponse:
    project = await _project(session, project_id)

    async def action() -> None:
        try:
            parsed = uuid.UUID(contractor_id)
        except ValueError as exc:
            raise ValidationError("Выберите подрядчика из списка.") from exc
        await directory.link_contractor(session, project, parsed)

    return await _apply(
        request, session, action, "Подрядчик привязан к проекту.", f"/refs/projects/{project_id}"
    )


@router.post("/projects/{project_id}/contractors/{contractor_id}/unlink", dependencies=CSRF)
async def unlink_contractor(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    project_id: uuid.UUID,
    contractor_id: uuid.UUID,
) -> RedirectResponse:
    project = await _project(session, project_id)
    return await _apply(
        request,
        session,
        lambda: directory.unlink_contractor(session, project, contractor_id),
        "Подрядчик больше не получает рассылки по проекту.",
        f"/refs/projects/{project_id}",
    )


# --- contractors ----------------------------------------------------------------------------


@router.get("/contractors")
async def contractors_page(
    request: Request, session: SessionDep, user: CurrentUser, edit: uuid.UUID | None = None
) -> Any:
    rows = await directory.list_contractors(session)
    return render(request, "refs/contractors.html", tab="contractors", rows=rows, edit=edit)


@router.post("/contractors", dependencies=CSRF)
async def create_contractor(
    request: Request, session: SessionDep, user: AdminUser, name: FormStr, email: FormStr
) -> RedirectResponse:
    return await _apply(
        request,
        session,
        lambda: directory.create_contractor(session, name, email),
        "Подрядчик добавлен.",
        "/refs/contractors",
    )


@router.post("/contractors/{contractor_id}", dependencies=CSRF)
async def update_contractor(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    contractor_id: uuid.UUID,
    name: FormStr,
    email: FormStr,
) -> RedirectResponse:
    contractor = await session.get(Contractor, contractor_id)
    if contractor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подрядчик не найден.")
    return await _apply(
        request,
        session,
        lambda: directory.update_contractor(session, contractor, name, email),
        "Подрядчик сохранён.",
        "/refs/contractors",
    )


# --- users ----------------------------------------------------------------------------------


@router.get("/users")
async def users_page(request: Request, session: SessionDep, user: CurrentUser) -> Any:
    return render(
        request,
        "refs/users.html",
        tab="users",
        rows=await users.list_users(session),
        roles=list(UserRole),
    )


@router.post("/users", dependencies=CSRF)
async def create_user(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    email: FormStr,
    full_name: FormStr,
    role: Annotated[UserRole, Form()],
) -> RedirectResponse:
    password = generate_password()

    async def action() -> None:
        created = await users.create_user(session, email, full_name, role, password)
        flash(request, f"Временный пароль для {created.email}: {password}", "secret")

    return await _apply(request, session, action, "Пользователь добавлен.", "/refs/users")


async def _user(session: AsyncSession, user_id: uuid.UUID) -> User:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден.")
    return target


@router.post("/users/{user_id}/reset-password", dependencies=CSRF)
async def reset_password(
    request: Request, session: SessionDep, user: AdminUser, user_id: uuid.UUID
) -> RedirectResponse:
    target = await _user(session, user_id)
    password = generate_password()

    async def action() -> None:
        await users.set_password(session, target, password)
        flash(request, f"Новый временный пароль для {target.email}: {password}", "secret")

    return await _apply(request, session, action, "Пароль сброшен.", "/refs/users")


@router.post("/users/{user_id}/active", dependencies=CSRF)
async def set_user_active(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    user_id: uuid.UUID,
    is_active: FormBool = False,
) -> RedirectResponse:
    target = await _user(session, user_id)
    return await _apply(
        request,
        session,
        lambda: users.set_active(session, target, is_active, acting=user),
        "Доступ восстановлен." if is_active else "Пользователь отключён.",
        "/refs/users",
    )


# --- production calendar --------------------------------------------------------------------


@router.get("/calendar")
async def calendar_page(
    request: Request, session: SessionDep, user: CurrentUser, year: int | None = None
) -> Any:
    year = year or date.today().year
    holidays = await directory.list_holidays(session, year)
    return render(
        request,
        "refs/calendar.html",
        tab="calendar",
        year=year,
        holidays=holidays,
        years=range(year - 1, year + 2),
    )


@router.post("/calendar", dependencies=CSRF)
async def set_holiday(
    request: Request,
    session: SessionDep,
    user: AdminUser,
    day: Annotated[date, Form()],
    is_workday: FormBool = False,
) -> RedirectResponse:
    return await _apply(
        request,
        session,
        lambda: directory.set_holiday(session, day, is_workday),
        "Дата сохранена в календаре.",
        f"/refs/calendar?year={day.year}",
    )


@router.post("/calendar/{day}/delete", dependencies=CSRF)
async def delete_holiday(
    request: Request, session: SessionDep, user: AdminUser, day: date
) -> RedirectResponse:
    return await _apply(
        request,
        session,
        lambda: directory.delete_holiday(session, day),
        "Дата удалена из календаря.",
        f"/refs/calendar?year={day.year}",
    )

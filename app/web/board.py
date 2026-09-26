"""CRM board (TZ 7.1) and notification card (TZ 7.3), as HTML pages and JSON (TZ 5)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionDep
from app.models import Channel, Corpus, Project
from app.services import board as boards
from app.services.workdays import local_date
from app.web.deps import CurrentUser
from app.web.templating import render

router = APIRouter()


def _today() -> date:
    return local_date(datetime.now(UTC), get_settings().app_timezone)


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def _pick_project(
    session: AsyncSession, project_id: uuid.UUID | None
) -> tuple[Project | None, list[Project]]:
    projects = list(
        await session.scalars(select(Project).order_by(Project.is_active.desc(), Project.name))
    )
    chosen = next((p for p in projects if p.id == project_id), None)
    return chosen or next(iter(projects), None), projects


def _filters(
    corpus_id: str | None, contractor_id: str | None, display: str | None, channel: str | None
) -> boards.Filters:
    displays = {d.value: d for d in boards.Display}
    channels = {c.value: c for c in Channel}
    return boards.Filters(
        corpus_id=_uuid(corpus_id),
        contractor_id=_uuid(contractor_id),
        display=displays.get(display or ""),
        channel=channels.get(channel or ""),
    )


@router.get("/")
async def board_page(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    project_id: str | None = None,
    corpus_id: str | None = None,
    contractor_id: str | None = None,
    display: str | None = None,
    channel: str | None = None,
    open: str | None = None,
) -> Any:
    project, projects = await _pick_project(session, _uuid(project_id))
    filters = _filters(corpus_id, contractor_id, display, channel)
    board = (
        await boards.build_board(session, get_settings(), project, _today(), filters)
        if project
        else None
    )
    corpuses = (
        list(
            await session.scalars(
                select(Corpus).where(Corpus.project_id == project.id).order_by(Corpus.name)
            )
        )
        if project
        else []
    )
    return render(
        request,
        "board.html",
        section="board",
        board=board,
        project=project,
        projects=projects,
        corpuses=corpuses,
        filters=filters,
        today=_today(),
        labels=boards.LABELS,
        short=boards.SHORT_LABELS,
        displays=list(boards.Display),
        open_cell=open,
        workdays=get_settings().deadline_workdays,
    )


@router.get("/notifications/{notification_id}")
async def card_page(
    request: Request, session: SessionDep, user: CurrentUser, notification_id: uuid.UUID
) -> Any:
    card = await boards.build_card(session, get_settings(), notification_id, _today())
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Уведомление не найдено.")
    return render(
        request,
        "card.html",
        section="board",
        card=card,
        labels=boards.LABELS,
        workdays=get_settings().deadline_workdays,
        tz=get_settings().app_timezone,
    )


# --- JSON (TZ section 5) --------------------------------------------------------------------


@router.get("/api/dashboard")
async def dashboard_api(
    session: SessionDep,
    user: CurrentUser,
    project_id: uuid.UUID,
    corpus_id: str | None = None,
    contractor_id: str | None = None,
    display: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден.")
    board = await boards.build_board(
        session,
        get_settings(),
        project,
        _today(),
        _filters(corpus_id, contractor_id, display, channel),
    )
    return {
        "project": {"id": str(project.id), "name": project.name},
        "counts": {d.value: board.counts.get(d, 0) for d in boards.Display},
        "columns": [
            {"sarex_link": c.sarex_link, "title": c.title, "first_sent": c.first_sent.isoformat()}
            for c in board.columns
        ],
        "corpuses": [
            {
                "id": str(corpus.id),
                "name": corpus.name,
                "cells": [
                    _cell_json(board.cells.get((corpus.id, column.sarex_link)))
                    for column in board.columns
                ],
            }
            for corpus in board.corpuses
        ],
    }


def _cell_json(cell: boards.Cell | None) -> dict[str, Any] | None:
    if cell is None:
        return None
    return {
        "total": cell.total,
        "acknowledged": cell.acknowledged,
        "worst": cell.worst.value,
        "items": [
            {
                "notification_id": str(i.notification.id),
                "contractor": i.contractor.name,
                "display": i.display.value,
                "workdays_elapsed": i.elapsed,
            }
            for i in cell.items
        ],
        "excluded": [c.name for c in cell.excluded],
    }


@router.get("/api/notifications/{notification_id}")
async def notification_api(
    session: SessionDep, user: CurrentUser, notification_id: uuid.UUID
) -> dict[str, Any]:
    card = await boards.build_card(session, get_settings(), notification_id, _today())
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Уведомление не найдено.")
    n = card.notification
    return {
        "id": str(n.id),
        "project": card.project.name,
        "corpus": card.corpus.name,
        "contractor": {"name": card.contractor.name, "email": card.contractor.email},
        "sarex_link": n.sarex_link,
        "status": n.status.value,
        "display": card.display.value,
        "sent_at": n.sent_at.isoformat(),
        "deadline_at": n.deadline_at.isoformat(),
        "ai_category": n.ai_category.value if n.ai_category else None,
        "ai_confidence": n.ai_confidence,
        "needs_manual_review": n.needs_manual_review,
        "events": [
            {
                "id": str(e.id),
                "type": e.type.value,
                "channel": e.channel.value,
                "created_at": e.created_at.isoformat(),
                "ai_category": e.ai_category.value if e.ai_category else None,
                "delivery": e.payload.get("delivery"),
            }
            for e in card.events
        ],
    }


@router.get("/api/notifications/{notification_id}/events/{event_id}")
async def event_api(
    session: SessionDep, user: CurrentUser, notification_id: uuid.UUID, event_id: uuid.UUID
) -> dict[str, Any]:
    card = await boards.build_card(session, get_settings(), notification_id, _today())
    event = next((e for e in card.events if e.id == event_id), None) if card else None
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено.")
    return {"id": str(event.id), "type": event.type.value, "raw_content": event.raw_content}

"""«Подтверждаю ознакомление» button from the email (TZ 4.2, section 5).

GET only shows a page: mail systems open links from emails automatically (Outlook Safe Links),
so the status changes only on POST from the page.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionDep
from app.models import Contractor, Corpus, Notification, NotificationStatus, Project
from app.services.ack_tokens import read_ack_token
from app.services.notifications import acknowledge_by_button
from app.web.templating import render

router = APIRouter(prefix="/ack")


async def _load(session: AsyncSession, token: str) -> Notification:
    notification_id = read_ack_token(get_settings(), token)
    notification = await session.get(Notification, notification_id) if notification_id else None
    if notification is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Ссылка недействительна или устарела. Ответьте на письмо, и координатор отметит "
            "ознакомление вручную.",
        )
    return notification


async def _page(
    request: Request, session: AsyncSession, notification: Notification, just_done: bool
) -> Any:
    return render(
        request,
        "ack.html",
        notification=notification,
        project=await session.get(Project, notification.project_id),
        corpus=await session.get(Corpus, notification.corpus_id),
        contractor=await session.get(Contractor, notification.contractor_id),
        done=notification.status is NotificationStatus.ACKNOWLEDGED,
        just_done=just_done,
    )


@router.get("/{token}")
async def ack_page(request: Request, session: SessionDep, token: str) -> Any:
    return await _page(request, session, await _load(session, token), just_done=False)


@router.post("/{token}")
async def ack_submit(request: Request, session: SessionDep, token: str) -> Any:
    notification = await _load(session, token)
    changed = await acknowledge_by_button(session, notification)
    await session.commit()
    return await _page(request, session, notification, just_done=changed)

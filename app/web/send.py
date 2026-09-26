"""«Отправить уведомление» (TZ 7.2): a mailing to all contractors of a corpus."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionDep
from app.models import Corpus, Project, User
from app.services import notifications
from app.services.errors import ValidationError
from app.services.workdays import local_date
from app.web.deps import CurrentUser
from app.web.mail_deps import Deliverer, get_deliverer
from app.web.session import flash, verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/send")


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _deadline_field(value: str) -> date | None:
    """Empty means the default deadline; a malformed date is an input error."""
    if not value:
        return None
    parsed = _date(value)
    if parsed is None:
        raise ValidationError("Укажите дату срока ответа.", "deadline")
    return parsed


async def _form_page(
    request: Request,
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID | None,
    corpus_id: uuid.UUID | None,
    sarex_link: str = "",
    message: str = "",
    selected: set[uuid.UUID] | None = None,
    error: ValidationError | None = None,
    deadline: date | None = None,
) -> Any:
    settings = get_settings()
    projects = list(
        await session.scalars(select(Project).where(Project.is_active).order_by(Project.name))
    )
    project = next((p for p in projects if p.id == project_id), None)
    if project is None and len(projects) == 1:
        project = projects[0]
    corpuses: list[Corpus] = []
    recipients: list[notifications.Recipient] = []
    if project is not None:
        corpuses = list(
            await session.scalars(
                select(Corpus)
                .where(Corpus.project_id == project.id, Corpus.is_active)
                .order_by(Corpus.name)
            )
        )
        if corpus_id not in {c.id for c in corpuses}:
            corpus_id = corpuses[0].id if len(corpuses) == 1 else None
        recipients = await notifications.recipients(session, corpus_id, sarex_link)
    if selected is None:
        selected = {r.contractor.id for r in recipients if not r.already_sent}
    now = datetime.now(UTC)
    default_deadline = local_date(
        await notifications.deadline_for(session, settings, now), settings.app_timezone
    )
    return render(
        request,
        "send.html",
        status_code=400 if error else 200,
        projects=projects,
        project=project,
        corpuses=corpuses,
        corpus_id=corpus_id,
        recipients=recipients,
        selected=selected,
        sarex_link=sarex_link,
        message=message,
        deadline=deadline or default_deadline,
        default_deadline=default_deadline,
        tomorrow=local_date(now, settings.app_timezone) + timedelta(days=1),
        workdays=settings.deadline_workdays,
        error=error,
    )


@router.get("")
async def send_page(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    project_id: str | None = None,
    corpus_id: str | None = None,
    sarex_link: str = "",
    message: str = "",
    deadline: str = "",
) -> Any:
    """Also reloaded when the corpus changes: its contractors become the recipients."""
    return await _form_page(
        request,
        session,
        user,
        _uuid(project_id),
        _uuid(corpus_id),
        sarex_link,
        message,
        deadline=_date(deadline),
    )


@router.get("/already-sent")
async def already_sent(
    session: SessionDep,
    user: CurrentUser,
    corpus_id: uuid.UUID,
    sarex_link: str = "",
) -> dict[str, list[str]]:
    """For the form script: who already got this link for this corpus."""
    recipients = await notifications.recipients(session, corpus_id, sarex_link)
    return {"already_sent": [str(r.contractor.id) for r in recipients if r.already_sent]}


@router.post("", dependencies=[Depends(verify_csrf)])
async def send_submit(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    background: BackgroundTasks,
    deliver: Annotated[Deliverer, Depends(get_deliverer)],
    project_id: Annotated[str, Form()],
    corpus_id: Annotated[str, Form()] = "",
    sarex_link: Annotated[str, Form()] = "",
    message: Annotated[str, Form()] = "",
    contractor_ids: Annotated[list[str] | None, Form()] = None,
    deadline: Annotated[str, Form()] = "",
) -> Any:
    chosen = [cid for cid in (_uuid(v) for v in contractor_ids or []) if cid]
    project = _uuid(project_id)
    corpus = _uuid(corpus_id)
    try:
        if project is None or corpus is None:
            raise ValidationError("Выберите проект и корпус.", "corpus_id")
        result = await notifications.create_mailing(
            session,
            get_settings(),
            initiator=user,
            project_id=project,
            corpus_id=corpus,
            sarex_link=sarex_link,
            message=message,
            contractor_ids=chosen,
            deadline=_deadline_field(deadline),
        )
        event_ids = [n.events[0].id for n in result.notifications]
        await session.commit()
    except ValidationError as error:
        await session.rollback()
        await session.refresh(user)  # rollback expires loaded objects; the page shows the user
        return await _form_page(
            request,
            session,
            user,
            project,
            corpus,
            sarex_link,
            message,
            set(chosen),
            error,
            deadline=_date(deadline),
        )

    background.add_task(deliver, event_ids)
    count = len(result.notifications)
    flash(request, f"Отправлено уведомлений: {count}. Письма уходят подрядчикам.")
    if result.skipped_already_sent:
        names = ", ".join(c.name for c in result.skipped_already_sent)
        flash(
            request, f"Уже получали эту ссылку по этому корпусу, повторно не отправлено: {names}."
        )
    return RedirectResponse(
        f"/send?project_id={project}&corpus_id={corpus}", status_code=status.HTTP_303_SEE_OTHER
    )

"""Notifications: creating mailings and changing statuses (TZ 4.1, 4.2).

Status changes happen only in this module (CLAUDE.md, business invariants).
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    Channel,
    Contractor,
    Corpus,
    CorpusContractor,
    EventType,
    Notification,
    NotificationEvent,
    NotificationStatus,
    Project,
    User,
)
from app.services.ack_tokens import ack_url
from app.services.errors import ValidationError
from app.services.mail.letters import initial_letter
from app.services.workdays import add_workdays, load_calendar, local_date

MAX_MESSAGE_LENGTH = 5000
MAX_LINK_LENGTH = 2000


def clean_sarex_link(value: str) -> str:
    link = value.strip()
    parts = urlsplit(link)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValidationError(
            "Вставьте ссылку на документацию в Sarex целиком, с https://.", "sarex_link"
        )
    if len(link) > MAX_LINK_LENGTH:
        raise ValidationError("Ссылка слишком длинная.", "sarex_link")
    return link


def clean_message(value: str | None) -> str | None:
    text = (value or "").strip().replace("\r\n", "\n")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValidationError(
            f"Сопроводительное сообщение — не длиннее {MAX_MESSAGE_LENGTH} символов.", "message"
        )
    return text or None


async def deadline_for(session: AsyncSession, settings: Settings, sent_at: datetime) -> datetime:
    """Deadline: N working days after sending, at `deadline_hour` local time (TZ 4.3)."""
    tz = ZoneInfo(settings.app_timezone)
    start = local_date(sent_at, settings.app_timezone)
    calendar = await load_calendar(session, start, start + timedelta(days=90))
    day = add_workdays(start, settings.deadline_workdays, calendar)
    return datetime.combine(day, time(settings.deadline_hour), tzinfo=tz).astimezone(UTC)


@dataclass(frozen=True)
class Recipient:
    contractor: Contractor
    already_sent: bool


async def recipients(
    session: AsyncSession,
    corpus_id: uuid.UUID | None,
    sarex_link: str | None,
) -> list[Recipient]:
    """Contractors assigned to the corpus; `already_sent` if it already got this link."""
    if corpus_id is None:
        return []
    contractors = list(
        await session.scalars(
            select(Contractor)
            .join(CorpusContractor, CorpusContractor.contractor_id == Contractor.id)
            .where(CorpusContractor.corpus_id == corpus_id)
            .order_by(Contractor.name)
        )
    )
    sent: set[uuid.UUID] = set()
    if sarex_link:
        sent = set(
            await session.scalars(
                select(Notification.contractor_id).where(
                    Notification.corpus_id == corpus_id,
                    Notification.sarex_link == sarex_link.strip(),
                )
            )
        )
    return [Recipient(c, c.id in sent) for c in contractors]


@dataclass(frozen=True)
class MailingResult:
    notifications: list[Notification]
    skipped_already_sent: list[Contractor]


async def create_mailing(
    session: AsyncSession,
    settings: Settings,
    *,
    initiator: User,
    project_id: uuid.UUID,
    corpus_id: uuid.UUID,
    sarex_link: str,
    message: str | None,
    contractor_ids: list[uuid.UUID],
    now: datetime | None = None,
) -> MailingResult:
    """One notification, `sent` event and queued letter per selected contractor (TZ 4.1).

    Letters are only queued here (`delivery = pending`); they are sent after the transaction
    is committed, see `app.services.mail.outbox`.
    """
    project = await session.get(Project, project_id)
    if project is None or not project.is_active:
        raise ValidationError("Выберите активный проект.", "project_id")
    corpus = await session.get(Corpus, corpus_id)
    if corpus is None or corpus.project_id != project.id or not corpus.is_active:
        raise ValidationError("Выберите корпус этого проекта.", "corpus_id")
    link = clean_sarex_link(sarex_link)
    text = clean_message(message)

    candidates = {r.contractor.id: r for r in await recipients(session, corpus.id, link)}
    chosen = [candidates[cid] for cid in dict.fromkeys(contractor_ids) if cid in candidates]
    if len(chosen) != len(set(contractor_ids)):
        raise ValidationError("Среди получателей есть подрядчик, не назначенный на этот корпус.")
    to_send = [r.contractor for r in chosen if not r.already_sent]
    skipped = [r.contractor for r in chosen if r.already_sent]
    if not to_send:
        raise ValidationError(
            "Некому отправлять: выберите хотя бы одного подрядчика, который ещё не получал эту "
            "ссылку по этому корпусу."
        )

    sent_at = now or datetime.now(UTC)
    deadline_at = await deadline_for(session, settings, sent_at)
    deadline_day: date = local_date(deadline_at, settings.app_timezone)
    created = []
    for contractor in to_send:
        notification = Notification(
            id=uuid.uuid4(),
            project_id=project.id,
            corpus_id=corpus.id,
            contractor_id=contractor.id,
            sarex_link=link,
            reply_token=secrets.token_hex(12),
            initiator_id=initiator.id,
            channel=Channel.EMAIL,
            status=NotificationStatus.SENT,
            sent_at=sent_at,
            deadline_at=deadline_at,
            reminder_count=0,
            message=text,
        )
        letter = initial_letter(
            settings,
            to=contractor.email,
            reply_token=notification.reply_token,
            project=project.name,
            corpus=corpus.name,
            sarex_link=link,
            message=text,
            deadline=deadline_day,
            ack_url=ack_url(settings, notification.id),
            initiator=initiator.full_name,
        )
        notification.events = [
            NotificationEvent(
                type=EventType.SENT,
                channel=Channel.EMAIL,
                raw_content=letter.raw_content,
                payload={
                    "to": letter.to,
                    "reply_to": letter.reply_to,
                    "subject": letter.subject,
                    "message_id": letter.message_id,
                    "text": letter.text,
                    "html": letter.html,
                    "delivery": "pending",
                    "attempts": 0,
                    "initiator_id": str(initiator.id),
                },
                created_at=sent_at,
            )
        ]
        session.add(notification)
        created.append(notification)
    await session.flush()
    return MailingResult(created, skipped)


async def acknowledge_by_button(
    session: AsyncSession, notification: Notification, now: datetime | None = None
) -> bool:
    """«Подтверждаю ознакомление» from the email. Returns False if already acknowledged."""
    if notification.status is NotificationStatus.ACKNOWLEDGED:
        return False
    moment = now or datetime.now(UTC)
    notification.status = NotificationStatus.ACKNOWLEDGED
    notification.acknowledged_at = moment
    notification.needs_manual_review = False
    session.add(
        NotificationEvent(
            notification_id=notification.id,
            type=EventType.REPLY_ACK,
            channel=Channel.EMAIL,
            raw_content="Подрядчик нажал «Подтверждаю ознакомление» в письме.",
            payload={"source": "button"},
            created_at=moment,
        )
    )
    await session.flush()
    return True

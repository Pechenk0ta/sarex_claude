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
from app.services.mail.letters import initial_letter, rejection_letter
from app.services.workdays import add_workdays, is_workday, load_calendar, local_date

MAX_MESSAGE_LENGTH = 5000
MAX_LINK_LENGTH = 2000
MAX_COMMENT_LENGTH = 2000
MAX_DEADLINE_DAYS = 365

STATUS_LABELS = {
    NotificationStatus.SENT: "Ожидает ответа",
    NotificationStatus.ACKNOWLEDGED: "Ознакомлен",
    NotificationStatus.HAS_QUESTIONS: "Есть вопросы",
    NotificationStatus.REJECTED: "Не принята",
    NotificationStatus.ESCALATED: "Эскалировано РП",
}
# Statuses a coordinator can set by hand; `escalated` is set only by the reminder job.
MANUAL_STATUSES = (
    NotificationStatus.SENT,
    NotificationStatus.ACKNOWLEDGED,
    NotificationStatus.HAS_QUESTIONS,
    NotificationStatus.REJECTED,
)


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


def deadline_at_day(settings: Settings, day: date) -> datetime:
    """The deadline moment for a deadline date: `deadline_hour` local time, in UTC."""
    tz = ZoneInfo(settings.app_timezone)
    return datetime.combine(day, time(settings.deadline_hour), tzinfo=tz).astimezone(UTC)


async def deadline_for(session: AsyncSession, settings: Settings, sent_at: datetime) -> datetime:
    """Default deadline: N working days after sending, at `deadline_hour` local time (TZ 4.3)."""
    start = local_date(sent_at, settings.app_timezone)
    calendar = await load_calendar(session, start, start + timedelta(days=90))
    return deadline_at_day(settings, add_workdays(start, settings.deadline_workdays, calendar))


async def check_deadline_day(session: AsyncSession, day: date, today: date) -> None:
    """A deadline chosen by the coordinator: a working day after today, within a year."""
    if day <= today:
        raise ValidationError("Срок ответа должен быть позже сегодняшнего дня.", "deadline")
    if day > today + timedelta(days=MAX_DEADLINE_DAYS):
        raise ValidationError("Срок ответа — не дальше чем через год.", "deadline")
    if not is_workday(day, await load_calendar(session, day, day)):
        raise ValidationError("Срок выпадает на выходной день. Выберите рабочий день.", "deadline")


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
    deadline: date | None = None,
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
    if deadline is None:
        deadline_at = await deadline_for(session, settings, sent_at)
    else:
        await check_deadline_day(session, deadline, local_date(sent_at, settings.app_timezone))
        deadline_at = deadline_at_day(settings, deadline)
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


def _clean_comment(value: str | None) -> str | None:
    text = (value or "").strip().replace("\r\n", "\n")
    if len(text) > MAX_COMMENT_LENGTH:
        raise ValidationError(f"Комментарий — не длиннее {MAX_COMMENT_LENGTH} символов.", "comment")
    return text or None


async def set_status(
    session: AsyncSession,
    settings: Settings,
    notification: Notification,
    new_status: NotificationStatus,
    *,
    user: User,
    comment: str | None = None,
    now: datetime | None = None,
) -> list[uuid.UUID]:
    """Manual status change by a coordinator (board or card, TZ 7.1, 7.3).

    «Не принята» also queues the letter to the initiator and the project manager, once per
    notification (TZ 4.2). Returns ids of queued letters, to deliver after commit.
    """
    if new_status not in MANUAL_STATUSES:
        raise ValidationError("Такой статус нельзя выставить вручную.", "status")
    note = _clean_comment(comment)
    old_status = notification.status
    if old_status is new_status and not notification.needs_manual_review:
        raise ValidationError(f"Статус уже «{STATUS_LABELS[new_status]}».", "status")
    moment = now or datetime.now(UTC)
    notification.status = new_status
    notification.needs_manual_review = False
    notification.acknowledged_at = moment if new_status is NotificationStatus.ACKNOWLEDGED else None
    notification.rejected_at = moment if new_status is NotificationStatus.REJECTED else None
    raw = (
        f"Статус изменён вручную: «{STATUS_LABELS[old_status]}» → «{STATUS_LABELS[new_status]}»."
        f"\nКто: {user.full_name}."
    )
    if note:
        raw += f"\nКомментарий: {note}"
    session.add(
        NotificationEvent(
            notification_id=notification.id,
            type=EventType.STATUS_CHANGED,
            channel=notification.channel,
            raw_content=raw,
            payload={
                "old_status": old_status.value,
                "new_status": new_status.value,
                "user_id": str(user.id),
                "user_name": user.full_name,
                "comment": note,
            },
            created_at=moment,
        )
    )
    letters: list[uuid.UUID] = []
    if new_status is NotificationStatus.REJECTED:
        event = await _queue_rejection_letter(session, settings, notification, raw, moment)
        if event is not None:
            letters.append(event)
    await session.flush()
    return letters


async def _queue_rejection_letter(
    session: AsyncSession,
    settings: Settings,
    notification: Notification,
    manual_note: str,
    moment: datetime,
) -> uuid.UUID | None:
    """«РД не принята» to the initiator and the PM, unless it was already sent (TZ 4.2)."""
    already = await session.scalar(
        select(NotificationEvent.id).where(
            NotificationEvent.notification_id == notification.id,
            NotificationEvent.type == EventType.REJECTION_NOTIFIED,
        )
    )
    if already:
        return None
    reply = await session.scalar(
        select(NotificationEvent)
        .where(
            NotificationEvent.notification_id == notification.id,
            NotificationEvent.type.in_(
                [EventType.REPLY_REJECTION, EventType.REPLY_QUESTION, EventType.REPLY_UNCLEAR]
            ),
        )
        .order_by(NotificationEvent.created_at.desc())
        .limit(1)
    )
    reply_text = manual_note
    if reply is not None:
        reply_text = f"{manual_note}\n\nПоследний ответ подрядчика:\n{reply.raw_content}"
    project = await session.get_one(Project, notification.project_id)
    corpus = await session.get_one(Corpus, notification.corpus_id)
    contractor = await session.get_one(Contractor, notification.contractor_id)
    initiator = await session.get_one(User, notification.initiator_id)
    letter = rejection_letter(
        settings,
        to=[initiator.email, project.project_manager_email],
        project=project.name,
        corpus=corpus.name,
        contractor=contractor.name,
        sarex_link=notification.sarex_link,
        sent_on=local_date(notification.sent_at, settings.app_timezone),
        reply_text=reply_text,
        card_url=f"{settings.app_base_url.rstrip('/')}/notifications/{notification.id}",
    )
    event = NotificationEvent(
        id=uuid.uuid4(),
        notification_id=notification.id,
        type=EventType.REJECTION_NOTIFIED,
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
        },
        created_at=moment,
    )
    session.add(event)
    return event.id


async def change_deadline(
    session: AsyncSession,
    settings: Settings,
    notification: Notification,
    day: date,
    *,
    user: User,
    now: datetime | None = None,
) -> None:
    """New deadline set by a coordinator. An escalated notification goes back to waiting and
    the reminders after the deadline start over."""
    if notification.status in (NotificationStatus.ACKNOWLEDGED, NotificationStatus.REJECTED):
        raise ValidationError("Ответ уже получен: срок менять не нужно.", "deadline")
    moment = now or datetime.now(UTC)
    tz = settings.app_timezone
    await check_deadline_day(session, day, local_date(moment, tz))
    old_day = local_date(notification.deadline_at, tz)
    if day == old_day:
        raise ValidationError("Срок и так такой.", "deadline")
    notification.deadline_at = deadline_at_day(settings, day)
    notification.reminder_count = 0  # reminders come after the new deadline again (TZ 4.3)
    raw = (
        f"Срок ответа изменён вручную: {old_day:%d.%m.%Y} → {day:%d.%m.%Y}.\nКто: {user.full_name}."
    )
    if notification.status is NotificationStatus.ESCALATED:
        notification.status = NotificationStatus.SENT
        raw += "\nСтатус «Эскалировано РП» снят: срок продлён."
    session.add(
        NotificationEvent(
            notification_id=notification.id,
            type=EventType.DEADLINE_CHANGED,
            channel=notification.channel,
            raw_content=raw,
            payload={
                "old_deadline": old_day.isoformat(),
                "new_deadline": day.isoformat(),
                "user_id": str(user.id),
                "user_name": user.full_name,
            },
            created_at=moment,
        )
    )
    await session.flush()


def mark_escalated(notification: Notification, moment: datetime) -> None:
    """The deadline passed without an answer (TZ 4.3). The event and the letter to the project
    manager are written by `app.services.reminders`."""
    notification.status = NotificationStatus.ESCALATED
    notification.escalated_at = moment

"""Daily reminders and escalation (TZ 4.3).

Runs once a working day. Contractors who have not answered get a reminder on the 1st and the
3rd working day (only before the deadline); when the deadline has passed, the notification is
escalated and the project manager gets one letter per mailing.

Idempotent: candidates are locked with `FOR UPDATE SKIP LOCKED` and re-read under the lock, and
every step moves `reminder_count` / `status` forward, so a second run on the same day finds
nothing to do. Letters are only queued here; they are sent after the commit by the outbox.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    Channel,
    Contractor,
    Corpus,
    EventType,
    Notification,
    NotificationEvent,
    NotificationStatus,
    Project,
    User,
)
from app.services.ack_tokens import ack_url
from app.services.mail.letters import (
    Letter,
    OverdueItem,
    escalation_letter,
    initial_letter,
)
from app.services.notifications import mark_escalated
from app.services.workdays import (
    Calendar,
    is_workday,
    load_calendar,
    local_date,
    workdays_between,
)


def next_action(
    notification: Notification, today: date, calendar: Calendar, settings: Settings
) -> EventType | None:
    """What the daily job does with a notification today, if anything.

    `calendar` must cover the sending day .. today. If the job missed days, it catches up
    with a single letter: the second reminder is sent instead of both.
    """
    if notification.status is not NotificationStatus.SENT or notification.needs_manual_review:
        return None  # answered, escalated already, or a reply waits for the coordinator
    tz = settings.app_timezone
    if today > local_date(notification.deadline_at, tz):
        return EventType.ESCALATED
    elapsed = workdays_between(local_date(notification.sent_at, tz), today, calendar)
    if notification.reminder_count < 2 and elapsed >= settings.second_reminder_workdays:
        return EventType.REMINDER_3
    if notification.reminder_count == 0 and elapsed >= settings.first_reminder_workdays:
        return EventType.REMINDER_1
    return None


@dataclass
class RunResult:
    reminders: int = 0
    escalated: int = 0
    letters: list[uuid.UUID] = field(default_factory=list)  # events to deliver after commit
    skipped_day_off: bool = False


def _letter_payload(letter: Letter, **extra: object) -> dict[str, object]:
    return {
        "to": letter.to,
        "reply_to": letter.reply_to,
        "subject": letter.subject,
        "message_id": letter.message_id,
        "text": letter.text,
        "html": letter.html,
        "delivery": "pending",
        "attempts": 0,
        **extra,
    }


def _card_url(settings: Settings, notification: Notification) -> str:
    return f"{settings.app_base_url.rstrip('/')}/notifications/{notification.id}"


async def run_reminders(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> RunResult:
    """One run of the daily job. The caller commits (`async with session.begin()`)."""
    moment = now or datetime.now(UTC)
    tz = settings.app_timezone
    today = local_date(moment, tz)
    result = RunResult()
    if not is_workday(today, await load_calendar(session, today, today)):
        result.skipped_day_off = True
        return result

    candidates = list(
        await session.scalars(
            select(Notification)
            .where(
                Notification.status == NotificationStatus.SENT,
                Notification.needs_manual_review.is_(False),
            )
            .order_by(Notification.sent_at, Notification.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    if not candidates:
        return result
    first_day = min(local_date(n.sent_at, tz) for n in candidates)
    calendar = await load_calendar(session, first_day, today)

    to_remind: list[tuple[Notification, EventType]] = []
    # One letter per mailing (and deadline: a single contractor's deadline may be extended).
    overdue: dict[tuple[uuid.UUID, str, datetime], list[Notification]] = defaultdict(list)
    for notification in candidates:
        action = next_action(notification, today, calendar, settings)
        if action is EventType.ESCALATED:
            key = (notification.corpus_id, notification.sarex_link, notification.deadline_at)
            overdue[key].append(notification)
        elif action is not None:
            to_remind.append((notification, action))

    first_letters = await _first_letter_ids([n.id for n, _ in to_remind], session)
    for notification, action in to_remind:
        result.letters.append(
            await _remind(session, settings, notification, action, first_letters, moment)
        )
        result.reminders += 1
    for group in overdue.values():
        result.letters.append(await _escalate(session, settings, group, today, calendar, moment))
        result.escalated += len(group)
    await session.flush()
    return result


async def _first_letter_ids(
    notification_ids: list[uuid.UUID], session: AsyncSession
) -> dict[uuid.UUID, str]:
    """Message-ID of the first letter of each notification: reminders reply to it."""
    if not notification_ids:
        return {}
    rows = await session.execute(
        select(NotificationEvent.notification_id, NotificationEvent.payload).where(
            NotificationEvent.notification_id.in_(notification_ids),
            NotificationEvent.type == EventType.SENT,
        )
    )
    return {nid: payload["message_id"] for nid, payload in rows if payload.get("message_id")}


async def _remind(
    session: AsyncSession,
    settings: Settings,
    notification: Notification,
    action: EventType,
    first_letters: dict[uuid.UUID, str],
    moment: datetime,
) -> uuid.UUID:
    project = await session.get_one(Project, notification.project_id)
    corpus = await session.get_one(Corpus, notification.corpus_id)
    contractor = await session.get_one(Contractor, notification.contractor_id)
    initiator = await session.get_one(User, notification.initiator_id)
    letter = initial_letter(
        settings,
        to=contractor.email,
        reply_token=notification.reply_token,
        project=project.name,
        corpus=corpus.name,
        sarex_link=notification.sarex_link,
        message=notification.message,
        deadline=local_date(notification.deadline_at, settings.app_timezone),
        ack_url=ack_url(settings, notification.id),
        initiator=initiator.full_name,
        reminder=True,
    )
    notification.reminder_count = 2 if action is EventType.REMINDER_3 else 1
    notification.last_reminder_at = moment
    event = NotificationEvent(
        id=uuid.uuid4(),
        notification_id=notification.id,
        type=action,
        channel=Channel.EMAIL,
        raw_content=letter.raw_content,
        payload=_letter_payload(letter, in_reply_to=first_letters.get(notification.id)),
        created_at=moment,
    )
    session.add(event)
    return event.id


async def _escalate(
    session: AsyncSession,
    settings: Settings,
    group: list[Notification],
    today: date,
    calendar: Calendar,
    moment: datetime,
) -> uuid.UUID:
    """One letter to the project manager per mailing; an `escalated` event on each notification.

    The letter is delivered from the first notification's event; the others keep its full text
    and a reference to it, so every card shows what the project manager received.
    """
    tz = settings.app_timezone
    head = group[0]
    project = await session.get_one(Project, head.project_id)
    corpus = await session.get_one(Corpus, head.corpus_id)
    initiator = await session.get_one(User, head.initiator_id)
    items = []
    for notification in group:
        contractor = await session.get_one(Contractor, notification.contractor_id)
        items.append(
            OverdueItem(
                contractor=contractor.name,
                email=contractor.email,
                workdays_without_answer=workdays_between(
                    local_date(notification.sent_at, tz), today, calendar
                ),
                card_url=_card_url(settings, notification),
            )
        )
    letter = escalation_letter(
        settings,
        to=project.project_manager_email,
        project=project.name,
        corpus=corpus.name,
        sarex_link=head.sarex_link,
        sent_on=local_date(head.sent_at, tz),
        deadline=local_date(head.deadline_at, tz),
        items=items,
        initiator=initiator.full_name,
    )
    letter_event_id = uuid.uuid4()
    for index, notification in enumerate(group):
        mark_escalated(notification, moment)
        payload: dict[str, object] = (
            _letter_payload(letter)
            if index == 0
            else {
                "to": letter.to,
                "subject": letter.subject,
                "letter_event_id": str(letter_event_id),
            }
        )
        session.add(
            NotificationEvent(
                id=letter_event_id if index == 0 else uuid.uuid4(),
                notification_id=notification.id,
                type=EventType.ESCALATED,
                channel=Channel.EMAIL,
                raw_content=letter.raw_content,
                payload=payload,
                created_at=moment,
            )
        )
    return letter_event_id

"""CRM board (TZ 7.1): corpus × Sarex link grid for one project, and the notification card
(TZ 7.3). Read-only; statuses shown on screen are derived here from stored data."""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    Channel,
    Contractor,
    Corpus,
    Notification,
    NotificationEvent,
    NotificationStatus,
    Project,
    ProjectContractor,
    User,
)
from app.services.workdays import Calendar, load_calendar, local_date, workdays_between

SOON_REMAINING_WORKDAYS = 5  # "истекает": this many working days or fewer left


class Display(StrEnum):
    """What the coordinator sees, most alarming first (TZ 7.1)."""

    REJECTED = "rej"
    REVIEW = "review"
    LATE = "late"
    SOON = "soon"
    QUESTIONS = "ask"
    WAITING = "wait"
    OK = "ok"


PRIORITY = list(Display)
LABELS = {
    Display.REJECTED: "Не принята",
    Display.REVIEW: "Требует проверки",
    Display.LATE: "Просрочено",
    Display.SOON: "Срок истекает",
    Display.QUESTIONS: "Есть вопросы",
    Display.WAITING: "Ожидание, в срок",
    Display.OK: "Ознакомлен",
}
SHORT_LABELS = {
    Display.REJECTED: "Не принята",
    Display.REVIEW: "Проверить",
    Display.LATE: "Просрочено",
    Display.SOON: "Истекает",
    Display.QUESTIONS: "Вопросы",
    Display.WAITING: "Ожидание",
    Display.OK: "Ознакомлен",
}


def display_status(
    notification: Notification, today: date, calendar: Calendar, timezone: str, deadline_days: int
) -> Display:
    if notification.status is NotificationStatus.REJECTED:
        return Display.REJECTED
    if notification.needs_manual_review:
        return Display.REVIEW
    if notification.status is NotificationStatus.ESCALATED:
        return Display.LATE
    if notification.status is NotificationStatus.HAS_QUESTIONS:
        return Display.QUESTIONS
    if notification.status is NotificationStatus.ACKNOWLEDGED:
        return Display.OK
    if today > local_date(notification.deadline_at, timezone):
        return Display.LATE
    elapsed = workdays_between(local_date(notification.sent_at, timezone), today, calendar)
    if deadline_days - elapsed <= SOON_REMAINING_WORKDAYS:
        return Display.SOON
    return Display.WAITING


@dataclass
class Item:
    notification: Notification
    contractor: Contractor
    display: Display
    elapsed: int  # working days since sending (until the reply, if there is one)
    replied_on: date | None


@dataclass
class Cell:
    items: list[Item]
    excluded: list[Contractor]

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def acknowledged(self) -> int:
        return sum(1 for i in self.items if i.display is Display.OK)

    @property
    def worst(self) -> Display:
        return min((i.display for i in self.items), key=PRIORITY.index)

    @property
    def worst_count(self) -> int:
        return sum(1 for i in self.items if i.display is self.worst)

    @property
    def segments(self) -> list[Display]:
        return sorted((i.display for i in self.items), key=PRIORITY.index)


@dataclass
class Column:
    sarex_link: str
    first_sent: date

    @property
    def title(self) -> str:
        """Short name from the link until the TZ gets a separate "set name" field."""
        path = urlsplit(self.sarex_link).path.rstrip("/")
        return path.rsplit("/", 1)[-1] or urlsplit(self.sarex_link).netloc


@dataclass
class Board:
    project: Project
    corpuses: list[Corpus]
    columns: list[Column]
    cells: dict[tuple[uuid.UUID, str], Cell]
    counts: Counter[Display] = field(default_factory=Counter)
    contractors: list[Contractor] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class Filters:
    corpus_id: uuid.UUID | None = None
    contractor_id: uuid.UUID | None = None
    display: Display | None = None
    channel: Channel | None = None


async def _calendar(session: AsyncSession, start: date, end: date) -> dict[date, bool]:
    return await load_calendar(session, start, end)


async def build_board(
    session: AsyncSession, settings: Settings, project: Project, today: date, filters: Filters
) -> Board:
    tz = settings.app_timezone
    corpuses = list(
        await session.scalars(
            select(Corpus).where(Corpus.project_id == project.id).order_by(Corpus.name)
        )
    )
    query = (
        select(Notification, Contractor)
        .join(Contractor, Contractor.id == Notification.contractor_id)
        .where(Notification.project_id == project.id)
        .order_by(Notification.sent_at, Contractor.name)
    )
    if filters.corpus_id:
        query = query.where(Notification.corpus_id == filters.corpus_id)
    if filters.contractor_id:
        query = query.where(Notification.contractor_id == filters.contractor_id)
    if filters.channel:
        query = query.where(Notification.channel == filters.channel)
    rows = (await session.execute(query)).all()

    project_contractors = list(
        await session.scalars(
            select(Contractor)
            .join(ProjectContractor, ProjectContractor.contractor_id == Contractor.id)
            .where(ProjectContractor.project_id == project.id)
            .order_by(Contractor.name)
        )
    )

    earliest = min((local_date(n.sent_at, tz) for n, _ in rows), default=today)
    calendar = await _calendar(session, earliest, today)

    columns: dict[str, Column] = {}
    cells: dict[tuple[uuid.UUID, str], Cell] = {}
    counts: Counter[Display] = Counter()
    for notification, contractor in rows:
        display = display_status(notification, today, calendar, tz, settings.deadline_workdays)
        if filters.display and display is not filters.display:
            continue
        sent_day = local_date(notification.sent_at, tz)
        reply_at = notification.acknowledged_at or notification.rejected_at
        replied_on = local_date(reply_at, tz) if reply_at else None
        elapsed = workdays_between(sent_day, replied_on or today, calendar)
        columns.setdefault(notification.sarex_link, Column(notification.sarex_link, sent_day))
        cell = cells.setdefault((notification.corpus_id, notification.sarex_link), Cell([], []))
        cell.items.append(Item(notification, contractor, display, elapsed, replied_on))
        counts[display] += 1

    if not (filters.contractor_id or filters.display or filters.channel):
        for cell in cells.values():
            got = {i.contractor.id for i in cell.items}
            cell.excluded = [c for c in project_contractors if c.id not in got]

    shown_corpuses = [
        c
        for c in corpuses
        if (filters.corpus_id is None or c.id == filters.corpus_id)
        and (c.is_active or any(key[0] == c.id for key in cells))
    ]
    return Board(
        project=project,
        corpuses=shown_corpuses,
        columns=sorted(columns.values(), key=lambda c: (c.first_sent, c.title)),
        cells=cells,
        counts=counts,
        contractors=project_contractors,
    )


@dataclass
class Card:
    notification: Notification
    project: Project
    corpus: Corpus
    contractor: Contractor
    initiator: User
    events: list[NotificationEvent]
    display: Display
    elapsed: int
    mailing_total: int
    mailing_acknowledged: int


async def build_card(
    session: AsyncSession, settings: Settings, notification_id: uuid.UUID, today: date
) -> Card | None:
    notification = await session.get(Notification, notification_id)
    if notification is None:
        return None
    tz = settings.app_timezone
    sent_day = local_date(notification.sent_at, tz)
    calendar = await _calendar(session, sent_day, max(today, sent_day))
    events = list(
        await session.scalars(
            select(NotificationEvent)
            .where(NotificationEvent.notification_id == notification.id)
            .order_by(NotificationEvent.created_at, NotificationEvent.id)
        )
    )
    mailing = list(
        await session.scalars(
            select(Notification).where(
                Notification.corpus_id == notification.corpus_id,
                Notification.sarex_link == notification.sarex_link,
            )
        )
    )
    reply_at = notification.acknowledged_at or notification.rejected_at
    project = await session.get_one(Project, notification.project_id)
    corpus = await session.get_one(Corpus, notification.corpus_id)
    contractor = await session.get_one(Contractor, notification.contractor_id)
    initiator = await session.get_one(User, notification.initiator_id)
    return Card(
        notification=notification,
        project=project,
        corpus=corpus,
        contractor=contractor,
        initiator=initiator,
        events=events,
        display=display_status(notification, today, calendar, tz, settings.deadline_workdays),
        elapsed=workdays_between(
            sent_day, local_date(reply_at, tz) if reply_at else today, calendar
        ),
        mailing_total=len(mailing),
        mailing_acknowledged=sum(1 for n in mailing if n.status is NotificationStatus.ACKNOWLEDGED),
    )

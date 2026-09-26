"""Demo data matching the approved mockups (`mockups/index.html`).

Run: `python -m app.scripts.seed_demo`. Safe to run twice: does nothing if the demo
project already exists. Not for production databases.
"""

import asyncio
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import (
    AiCategory,
    Contractor,
    Corpus,
    EventType,
    Holiday,
    Notification,
    NotificationEvent,
    NotificationStatus,
    Project,
    ProjectContractor,
    User,
    UserRole,
)
from app.services.workdays import add_workdays, workdays_between

DEMO_PROJECT = "ЖК «Северная долина», 3-я очередь"
DEADLINE_WORKDAYS = 10
DEMO_TODAY = date(2026, 9, 26)

# Example calendar entries; verify against the government decree before real use.
HOLIDAYS_2026 = [
    *(date(2026, 1, d) for d in (1, 2, 5, 6, 7, 8)),
    date(2026, 2, 23),
    date(2026, 3, 9),
    date(2026, 5, 1),
    date(2026, 5, 11),
    date(2026, 6, 12),
    date(2026, 11, 4),
    date(2026, 12, 31),
]

CONTRACTORS = [
    ("ООО «СтройМонолит»", "pto@stroymonolit.ru"),
    ("ООО «ТеплоМонтаж»", "info@teplomontazh.ru"),
    ("ООО «АкваИнж»", "pto@akvainzh.ru"),
    ("ООО «ЭлектроСети-Сервис»", "eom@es-service.ru"),
    ("ООО «ФасадПро»", "tender@fasadpro.ru"),
]
UNLINKED_CONTRACTOR = ("ООО «ЛифтСтрой»", "office@liftstroy.ru")

USERS = [
    ("a.smirnova@company-domain.ru", "Смирнова Анна Викторовна", UserRole.COORDINATOR, True),
    ("m.orlov@company-domain.ru", "Орлов Максим Андреевич", UserRole.COORDINATOR, True),
    ("e.belova@company-domain.ru", "Белова Екатерина Олеговна", UserRole.COORDINATOR, True),
    ("p.kuznetsov@company-domain.ru", "Кузнецов Павел Романович", UserRole.ADMIN, True),
    ("o.grigoriev@company-domain.ru", "Григорьев Олег Викторович", UserRole.COORDINATOR, False),
]

CORPUSES = ["Корпус 1 · секции 1–3", "Корпус 2 · секции 4–5", "Корпус 3 · секции 6–8"]
CORPUS_WITHOUT_MAILINGS = "Корпус 4 · паркинг"

SETS = [  # (short name, sent date, Sarex link)
    ("АР", date(2026, 9, 2), "https://sarex.example.ru/project/sd-3/docs/AR-rev3"),
    ("КЖ.1", date(2026, 9, 11), "https://sarex.example.ru/project/sd-3/docs/KZH1-rev2"),
    ("ОВ", date(2026, 9, 15), "https://sarex.example.ru/project/sd-3/docs/OV-rev1"),
    ("ВК", date(2026, 9, 18), "https://sarex.example.ru/project/sd-3/docs/VK-rev1"),
    ("ЭОМ", date(2026, 9, 23), "https://sarex.example.ru/project/sd-3/docs/EOM-rev0"),
]


@dataclass(frozen=True)
class Outcome:
    """What happened with one contractor's notification in the demo."""

    kind: str  # ok | ask | rej | review | wait | late | excluded
    reply_after: int = 0  # working days after sending


def OK(after: int) -> Outcome:
    return Outcome("ok", after)


def ASK(after: int) -> Outcome:
    return Outcome("ask", after)


def REJ(after: int) -> Outcome:
    return Outcome("rej", after)


WAIT, LATE, REVIEW, EXCL = (
    Outcome("wait"),
    Outcome("late"),
    Outcome("review", 7),
    Outcome("excluded"),
)

# corpus index -> set index -> outcome per contractor (order of CONTRACTORS); None = not sent.
GRID: dict[int, list[list[Outcome] | None]] = {
    0: [
        [OK(1), OK(2), OK(1), OK(3), LATE],
        [OK(1), OK(1), OK(2), OK(1), OK(4)],
        [OK(2), OK(2), ASK(3), OK(1), REJ(6)],
        [OK(1), WAIT, OK(2), WAIT, EXCL],
        [WAIT, WAIT, OK(1), WAIT, WAIT],
    ],
    1: [
        [OK(2), OK(1), OK(1), OK(2), OK(3)],
        [REVIEW, OK(1), OK(2), OK(1), OK(2)],
        [OK(1), ASK(4), OK(1), OK(2), OK(1)],
        [OK(1), OK(2), WAIT, OK(1), OK(3)],
        None,
    ],
    2: [
        [OK(1), OK(1), OK(2), OK(1), ASK(2)],
        None,
        [OK(1), OK(3), OK(2), OK(1), OK(1)],
        None,
        [OK(1), WAIT, WAIT, WAIT, WAIT],
    ],
}

REPLIES = {
    "ok": "Добрый день. С документацией ознакомлены, замечаний нет.",
    "ask": "Добрый день. Уточните, пожалуйста, марку бетона для узла 3 на листе 7.",
    "rej": (
        "Документацию не принимаем: отсутствуют листы 12–14, в производство работ не допускается."
    ),
    "review": (
        "Добрый день.\nДокументацию получили, передали на участок.\n"
        "По узлу 4 уточним позже, сейчас смотрим с прорабом."
    ),
}


def _at(day: date, hour: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=tz)


def _letter(set_name: str, corpus: str, link: str, deadline: date) -> str:
    return (
        f"Тема: РД {set_name} · {DEMO_PROJECT}, {corpus} · подтвердите ознакомление\n\n"
        f"Добрый день!\n\nВыпущен комплект рабочей документации {set_name} по проекту "
        f"{DEMO_PROJECT}, {corpus}.\n\nДокументация: {link}\n\n"
        f"Пожалуйста, подтвердите ознакомление до {deadline:%d.%m.%Y}."
    )


async def seed(session: AsyncSession, today: date = DEMO_TODAY) -> bool:
    """Insert demo data. Returns False if it is already there."""
    exists = await session.scalar(select(Project.id).where(Project.name == DEMO_PROJECT))
    if exists is not None:
        return False

    tz = ZoneInfo(get_settings().app_timezone)
    calendar = {day: False for day in HOLIDAYS_2026}
    session.add_all(Holiday(date=day, is_workday=False) for day in HOLIDAYS_2026)

    users = [
        User(email=email, full_name=name, role=role, is_active=active)
        for email, name, role, active in USERS
    ]
    project = Project(
        name=DEMO_PROJECT,
        address="г. Санкт-Петербург, Парголово, ул. Николая Рубцова, участок 12",
        project_manager_email="i.petrov@company-domain.ru",
    )
    session.add_all(
        [
            Project(
                name="ЖК «Речной квартал»", project_manager_email="s.volkova@company-domain.ru"
            ),
            Project(
                name="БЦ «Литейный»",
                project_manager_email="i.petrov@company-domain.ru",
                is_active=False,
            ),
        ]
    )
    corpuses = [Corpus(project=project, name=name) for name in CORPUSES]
    corpuses.append(Corpus(project=project, name=CORPUS_WITHOUT_MAILINGS))
    contractors = [Contractor(name=name, email=email) for name, email in CONTRACTORS]
    session.add(Contractor(name=UNLINKED_CONTRACTOR[0], email=UNLINKED_CONTRACTOR[1]))
    session.add_all([*users, project, *corpuses, *contractors])
    await session.flush()
    session.add_all(
        ProjectContractor(project_id=project.id, contractor_id=c.id) for c in contractors
    )

    coordinator = users[0]
    for corpus_index, row in GRID.items():
        corpus = corpuses[corpus_index]
        for (set_name, sent_day, link), cell in zip(SETS, row, strict=True):
            if cell is None:
                continue
            deadline_day = add_workdays(sent_day, DEADLINE_WORKDAYS, calendar)
            for contractor, outcome in zip(contractors, cell, strict=True):
                if outcome.kind == "excluded":
                    continue
                session.add(
                    _notification(
                        project,
                        corpus,
                        contractor,
                        coordinator,
                        set_name,
                        link,
                        sent_day,
                        deadline_day,
                        outcome,
                        calendar,
                        today,
                        tz,
                    )
                )
    await session.flush()
    return True


def _notification(
    project: Project,
    corpus: Corpus,
    contractor: Contractor,
    coordinator: User,
    set_name: str,
    link: str,
    sent_day: date,
    deadline_day: date,
    outcome: Outcome,
    calendar: dict[date, bool],
    today: date,
    tz: ZoneInfo,
) -> Notification:
    sent_at = _at(sent_day, 10, tz)
    n = Notification(
        project_id=project.id,
        corpus_id=corpus.id,
        contractor_id=contractor.id,
        sarex_link=link,
        reply_token=secrets.token_urlsafe(12),
        initiator_id=coordinator.id,
        sent_at=sent_at,
        deadline_at=_at(deadline_day, 18, tz),
        status=NotificationStatus.SENT,
        reminder_count=0,
    )
    events = [
        NotificationEvent(
            type=EventType.SENT,
            raw_content=_letter(set_name, corpus.name, link, deadline_day),
            payload={"to": contractor.email},
            created_at=sent_at,
        )
    ]
    reply_day = add_workdays(sent_day, outcome.reply_after, calendar)

    # Reminders on working days 1 and 3 if no reply by then.
    for number, event_type in ((1, EventType.REMINDER_1), (3, EventType.REMINDER_3)):
        reminder_day = add_workdays(sent_day, number, calendar)
        replied_before = (
            outcome.kind in ("ok", "ask", "rej", "review") and reply_day <= reminder_day
        )
        if reminder_day <= today and not replied_before:
            n.reminder_count = number if number == 1 else 2
            n.last_reminder_at = _at(reminder_day, 9, tz)
            events.append(
                NotificationEvent(
                    type=event_type,
                    raw_content=(
                        f"Повторно: РД {set_name}, {corpus.name}. Подтвердите ознакомление."
                    ),
                    created_at=n.last_reminder_at,
                )
            )

    reply_at = _at(reply_day, 15, tz)
    if outcome.kind == "ok":
        n.status, n.acknowledged_at, n.ai_category, n.ai_confidence = (
            NotificationStatus.ACKNOWLEDGED,
            reply_at,
            AiCategory.ACKNOWLEDGEMENT,
            0.97,
        )
        events.append(_reply(EventType.REPLY_ACK, AiCategory.ACKNOWLEDGEMENT, 0.97, "ok", reply_at))
    elif outcome.kind == "ask":
        n.status, n.ai_category, n.ai_confidence = (
            NotificationStatus.HAS_QUESTIONS,
            AiCategory.QUESTION,
            0.91,
        )
        events.append(_reply(EventType.REPLY_QUESTION, AiCategory.QUESTION, 0.91, "ask", reply_at))
    elif outcome.kind == "rej":
        n.status, n.rejected_at, n.ai_category, n.ai_confidence = (
            NotificationStatus.REJECTED,
            reply_at,
            AiCategory.REJECTION,
            0.93,
        )
        events.append(
            _reply(EventType.REPLY_REJECTION, AiCategory.REJECTION, 0.93, "rej", reply_at)
        )
        events.append(
            NotificationEvent(
                type=EventType.REJECTION_NOTIFIED,
                payload={"to": [coordinator.email, project.project_manager_email]},
                created_at=reply_at + timedelta(minutes=1),
            )
        )
    elif outcome.kind == "review":
        n.ai_category, n.ai_confidence, n.needs_manual_review = AiCategory.UNCLEAR, 0.54, True
        events.append(_reply(EventType.REPLY_UNCLEAR, AiCategory.UNCLEAR, 0.54, "review", reply_at))
    elif outcome.kind == "late" and workdays_between(sent_day, today, calendar) > DEADLINE_WORKDAYS:
        escalation_day = add_workdays(sent_day, DEADLINE_WORKDAYS + 1, calendar)
        n.status, n.escalated_at = NotificationStatus.ESCALATED, _at(escalation_day, 9, tz)
        events.append(
            NotificationEvent(
                type=EventType.ESCALATED,
                payload={"to": project.project_manager_email},
                created_at=n.escalated_at,
            )
        )

    n.events = events
    return n


def _reply(
    event_type: EventType, category: AiCategory, confidence: float, kind: str, at: datetime
) -> NotificationEvent:
    return NotificationEvent(
        type=event_type,
        raw_content=REPLIES[kind],
        ai_category=category,
        payload={"ai_confidence": confidence, "classifier": "demo"},
        created_at=at,
    )


async def main() -> None:
    async with get_sessionmaker()() as session, session.begin():
        created = await seed(session)
    print("Demo data created." if created else "Demo data already present, nothing to do.")


if __name__ == "__main__":
    asyncio.run(main())

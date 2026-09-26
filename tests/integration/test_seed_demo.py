from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CorpusContractor,
    EventType,
    Notification,
    NotificationEvent,
    NotificationStatus,
)
from app.scripts.seed_demo import seed


async def _count_by_status(session: AsyncSession) -> dict[NotificationStatus, int]:
    rows = await session.execute(
        select(Notification.status, func.count()).group_by(Notification.status)
    )
    return {status: count for status, count in rows.all()}


async def test_demo_data_matches_mockup_board(session: AsyncSession) -> None:
    assert await seed(session) is True

    total = await session.scalar(select(func.count()).select_from(Notification))
    assert total == 59  # mockup: "59 уведомлений"
    counts = await _count_by_status(session)
    assert counts[NotificationStatus.ACKNOWLEDGED] == 42
    assert counts[NotificationStatus.HAS_QUESTIONS] == 3
    assert counts[NotificationStatus.REJECTED] == 1
    assert counts[NotificationStatus.ESCALATED] == 1
    review = await session.scalar(
        select(func.count()).select_from(Notification).where(Notification.needs_manual_review)
    )
    assert review == 1
    assert await session.scalar(select(func.count()).select_from(CorpusContractor)) == 3 * 5 + 2


async def test_every_notification_has_sent_event_and_rejection_notified(
    session: AsyncSession,
) -> None:
    await seed(session)

    without_sent = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            ~Notification.events.any(NotificationEvent.type == EventType.SENT),
        )
    )
    assert without_sent == 0
    rejected = await session.scalar(
        select(Notification).where(Notification.status == NotificationStatus.REJECTED)
    )
    assert rejected is not None
    await session.refresh(rejected, ["events"])
    assert EventType.REJECTION_NOTIFIED in [e.type for e in rejected.events]


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    assert await seed(session) is True
    assert await seed(session) is False
    assert await session.scalar(select(func.count()).select_from(Notification)) == 59

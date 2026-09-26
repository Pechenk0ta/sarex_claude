"""Delivery of queued letters (events with payload.delivery = "pending").

Letters are sent only after the transaction that created them is committed, so a crash
never leaves a letter sent without its record. Each event is locked while it is being sent
(`FOR UPDATE SKIP LOCKED`), so the web process and the worker never send the same letter twice.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import NotificationEvent
from app.services.mail.letters import to_email_message
from app.services.mail.sender import MailSendError, Sender

logger = logging.getLogger(__name__)
BATCH = 50


async def deliver_pending(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    sender: Sender,
    event_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    """Send pending letters; returns how many were sent."""
    sent = 0
    tried: list[uuid.UUID] = []
    for _ in range(BATCH):
        async with sessions() as session, session.begin():
            query = (
                select(NotificationEvent)
                .where(NotificationEvent.payload["delivery"].astext == "pending")
                .order_by(NotificationEvent.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if event_ids is not None:
                query = query.where(NotificationEvent.id.in_(event_ids))
            if tried:
                query = query.where(NotificationEvent.id.not_in(tried))
            event = await session.scalar(query)
            if event is None:
                break
            tried.append(event.id)
            payload = dict(event.payload)
            try:
                await sender.send(
                    to_email_message(
                        settings,
                        to=payload["to"],
                        subject=payload["subject"],
                        text=payload["text"],
                        html=payload["html"],
                        reply_to=payload["reply_to"],
                        message_id=payload["message_id"],
                    )
                )
            except MailSendError as error:
                payload["attempts"] = int(payload.get("attempts", 0)) + 1
                payload["last_error"] = str(error)[:500]
                if payload["attempts"] >= settings.mail_max_attempts:
                    payload["delivery"] = "failed"
                    logger.error(
                        "Letter %s failed after %s attempts", event.id, payload["attempts"]
                    )
                event.payload = payload
                if event_ids is not None:
                    # Inline attempt right after sending the form: leave retries to the worker.
                    continue
                break  # mail server is down: stop and retry on the next run
            payload["delivery"] = "sent"
            payload["attempts"] = int(payload.get("attempts", 0)) + 1
            payload["delivered_at"] = datetime.now(UTC).isoformat()
            payload.pop("last_error", None)
            event.payload = payload
            sent += 1
    return sent

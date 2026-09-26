"""Mail delivery wiring for web requests; overridden in tests."""

import uuid
from collections.abc import Awaitable, Callable, Sequence

from app.config import get_settings
from app.db import get_sessionmaker
from app.services.mail.outbox import deliver_pending
from app.services.mail.sender import SmtpSender

Deliverer = Callable[[Sequence[uuid.UUID]], Awaitable[object]]


async def _deliver_now(event_ids: Sequence[uuid.UUID]) -> None:
    settings = get_settings()
    await deliver_pending(get_sessionmaker(), settings, SmtpSender(settings), event_ids)


def get_deliverer() -> Deliverer:
    """First delivery attempt right after the mailing is committed; the worker retries."""
    return _deliver_now

"""Entry point of the `worker` container: scheduled jobs (reminders, inbound mail)."""

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db import get_sessionmaker
from app.services.mail.outbox import deliver_pending
from app.services.mail.sender import SmtpSender

logger = logging.getLogger("app.worker")


def build_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.app_timezone)
    scheduler.add_job(
        deliver_queued_letters,
        "interval",
        minutes=2,
        id="deliver_queued_letters",
        max_instances=1,
        coalesce=True,
    )
    # Reminders (stage 6) and inbound mail (stage 7) are added later.
    return scheduler


async def deliver_queued_letters() -> None:
    settings = get_settings()
    sent = await deliver_pending(get_sessionmaker(), settings, SmtpSender(settings))
    if sent:
        logger.info("Delivered %s queued letters", sent)


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Worker started, timezone %s", settings.app_timezone)
    await stop.wait()
    scheduler.shutdown(wait=False)
    logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(run())

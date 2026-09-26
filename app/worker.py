"""Entry point of the `worker` container: scheduled jobs (reminders, inbound mail)."""

import asyncio
import logging
import signal
from datetime import datetime, time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db import get_sessionmaker
from app.services.mail.outbox import deliver_pending
from app.services.mail.sender import SmtpSender
from app.services.reminders import RunResult, run_reminders

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
    scheduler.add_job(
        send_reminders,
        "cron",
        hour=settings.reminders_hour,
        minute=settings.reminders_minute,
        id="reminders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    if catch_up_needed(datetime.now(ZoneInfo(settings.app_timezone))):
        # Restarted after today's run time: run now; a run that already happened is a no-op.
        scheduler.add_job(send_reminders, id="reminders_catch_up")
    # Inbound mail (stage 7) is added later.
    return scheduler


def catch_up_needed(local_now: datetime) -> bool:
    """After today's reminders time, but not in the evening: letters at night look like spam."""
    settings = get_settings()
    start = time(settings.reminders_hour, settings.reminders_minute)
    return start <= local_now.time() < time(20, 0)


async def send_reminders() -> RunResult:
    """Reminders and escalation (TZ 4.3); letters are sent after the commit."""
    settings = get_settings()
    sessions = get_sessionmaker()
    async with sessions() as session, session.begin():
        result = await run_reminders(session, settings)
    if result.skipped_day_off:
        logger.info("Reminders: day off, nothing to do")
        return result
    if result.letters:
        await deliver_pending(sessions, settings, SmtpSender(settings), result.letters)
    logger.info(
        "Reminders: %s reminders, %s notifications escalated", result.reminders, result.escalated
    )
    return result


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

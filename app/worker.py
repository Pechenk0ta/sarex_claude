"""Entry point of the `worker` container: scheduled jobs (reminders, inbound mail)."""

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings

logger = logging.getLogger("app.worker")


def build_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.app_timezone)
    # Jobs are registered in later stages: reminders (stage 6), inbound mail (stage 7).
    return scheduler


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

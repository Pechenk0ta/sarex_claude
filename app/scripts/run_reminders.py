"""Run the daily reminders job once, now: `python -m app.scripts.run_reminders`.

The worker runs it every working day on its own; this command is for checking after an update.
Running it twice on the same day sends nothing new.
"""

import asyncio
import logging

from app.config import get_settings
from app.worker import send_reminders


async def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    result = await send_reminders()
    if result.skipped_day_off:
        print("Сегодня выходной по производственному календарю: напоминания не отправляются.")
        return
    print(f"Напоминаний: {result.reminders}. Эскалировано уведомлений: {result.escalated}.")


if __name__ == "__main__":
    asyncio.run(main())

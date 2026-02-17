from __future__ import annotations

import logging
from datetime import time, timezone

from telegram import BotCommand
from telegram.ext import Application

from bot.ai import AICoach
from bot.config import load_settings
from bot.db import MongoStore
from bot.handlers import build_handlers
from bot.jobs import chores_eod_confirmation_job, chores_morning_job, daily_checkin_job, weekly_review_job


logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


WEEKDAY_MAP = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


async def _register_telegram_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Initialize bot and show overview"),
            BotCommand("help", "Show all commands"),
            BotCommand("add", "Add a task (interactive or quick add)"),
            BotCommand("list", "List tasks with Done/Delete actions"),
            BotCommand("chores", "Show recurring weekend chores"),
            BotCommand("goal", "Show or update main goal"),
            BotCommand("checkin", "Run coaching check-in now"),
            BotCommand("review", "Run weekly-style review now"),
            BotCommand("improve", "Analyze productivity patterns and improvements"),
            BotCommand("cancel", "Cancel current /add flow"),
        ]
    )


def main() -> None:
    settings = load_settings()
    store = MongoStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db)
    store.ping()
    ai = AICoach(api_key=settings.openai_api_key, model=settings.openai_model)

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_register_telegram_commands)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["store"] = store
    application.bot_data["ai"] = ai

    for handler in build_handlers():
        application.add_handler(handler)

    checkin_time = time(hour=settings.checkin_hour_utc, minute=0, tzinfo=timezone.utc)
    application.job_queue.run_daily(
        callback=daily_checkin_job,
        time=checkin_time,
        name="daily-checkin",
    )
    chores_morning_time = time(hour=settings.chores_morning_hour_utc, minute=0, tzinfo=timezone.utc)
    application.job_queue.run_daily(
        callback=chores_morning_job,
        time=chores_morning_time,
        name="chores-morning",
    )
    chores_eod_time = time(hour=settings.chores_confirm_hour_utc, minute=0, tzinfo=timezone.utc)
    application.job_queue.run_daily(
        callback=chores_eod_confirmation_job,
        time=chores_eod_time,
        name="chores-end-of-day",
    )
    weekly_time = time(hour=settings.weekly_review_hour_utc, minute=0, tzinfo=timezone.utc)
    application.job_queue.run_daily(
        callback=weekly_review_job,
        time=weekly_time,
        days=(WEEKDAY_MAP[settings.weekly_review_day],),
        name="weekly-review",
    )

    logger.info("Bot started.")
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()

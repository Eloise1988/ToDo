from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    mongodb_uri: str
    mongodb_db: str
    openai_api_key: str
    openai_model: str
    checkin_hour_utc: int
    chores_morning_hour_utc: int
    chores_confirm_hour_utc: int
    weekly_review_day: str
    weekly_review_hour_utc: int
    stale_task_days: int


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer. Got: {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}. Got: {value}")
    return value


def load_settings() -> Settings:
    custom_env = Path(os.getenv("TODO_ENV_FILE", "~/.config/todo.env")).expanduser()
    if custom_env.is_file():
        load_dotenv(dotenv_path=custom_env, override=False)
    else:
        load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required.")

    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017").strip()
    mongodb_db = os.getenv("MONGODB_DB", "todo_coach_bot").strip()

    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    checkin_hour_utc = _int_env("CHECKIN_HOUR_UTC", 16, 0, 23)
    chores_morning_hour_utc = _int_env("CHORES_MORNING_HOUR_UTC", 8, 0, 23)
    chores_confirm_hour_utc = _int_env("CHORES_CONFIRM_HOUR_UTC", 20, 0, 23)
    weekly_review_day = os.getenv("WEEKLY_REVIEW_DAY", "sun").strip().lower()
    if weekly_review_day not in _VALID_DAYS:
        raise ValueError(f"WEEKLY_REVIEW_DAY must be one of {_VALID_DAYS}. Got: {weekly_review_day!r}")
    weekly_review_hour_utc = _int_env("WEEKLY_REVIEW_HOUR_UTC", 17, 0, 23)
    stale_task_days = _int_env("STALE_TASK_DAYS", 7, 1, 365)

    return Settings(
        telegram_bot_token=telegram_bot_token,
        mongodb_uri=mongodb_uri,
        mongodb_db=mongodb_db,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        checkin_hour_utc=checkin_hour_utc,
        chores_morning_hour_utc=chores_morning_hour_utc,
        chores_confirm_hour_utc=chores_confirm_hour_utc,
        weekly_review_day=weekly_review_day,
        weekly_review_hour_utc=weekly_review_hour_utc,
        stale_task_days=stale_task_days,
    )

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.prompts import COACH_SYSTEM_PROMPT, build_checkin_prompt, fallback_coaching_message


logger = logging.getLogger(__name__)
WEEKEND_DAYS = {5, 6}  # Saturday, Sunday


def generate_coaching_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, weekly: bool = False) -> str:
    store = context.application.bot_data["store"]
    settings = context.application.bot_data["settings"]
    ai = context.application.bot_data["ai"]

    profile = store.get_user_profile(user_id)
    main_goal = profile.get("main_goal", "make money")
    active_todos = store.list_active_todos(user_id, limit=30)
    stale_todos = store.get_stale_todos(user_id, stale_days=settings.stale_task_days, limit=10)
    overdue_todos = store.get_overdue_todos(user_id, limit=10)
    stats = store.get_stats(user_id)
    recent_notes = store.get_recent_journal_entries(user_id, limit=10)

    prompt = build_checkin_prompt(
        main_goal=main_goal,
        active_todos=active_todos,
        stale_todos=stale_todos,
        overdue_todos=overdue_todos,
        stats=stats,
        recent_notes=recent_notes,
        stale_days=settings.stale_task_days,
        weekly=weekly,
    )
    ai_message = ai.generate(COACH_SYSTEM_PROMPT, prompt)
    if ai_message:
        return _normalize_coaching_output(ai_message)

    return _normalize_coaching_output(
        fallback_coaching_message(
        main_goal=main_goal,
        active_todos=active_todos,
        stale_todos=stale_todos,
        overdue_todos=overdue_todos,
        )
    )


async def daily_checkin_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = context.application.bot_data["store"]
    for user_id in store.list_user_ids():
        try:
            message = generate_coaching_message(context, user_id=user_id, weekly=False)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Daily Check-in\n\n{message}",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Daily check-in failed for user %s: %s", user_id, exc)


async def weekly_review_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = context.application.bot_data["store"]
    for user_id in store.list_user_ids():
        try:
            message = generate_coaching_message(context, user_id=user_id, weekly=True)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Weekly Review\n\n{message}",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Weekly review failed for user %s: %s", user_id, exc)


def _format_due_rows(due_chores: list[dict]) -> str:
    lines: list[str] = []
    for chore in due_chores:
        name = chore.get("name", "")
        next_due = chore.get("next_due_date")
        if next_due:
            due_day = next_due.astimezone(timezone.utc).strftime("%Y-%m-%d")
        else:
            due_day = "n/a"
        lines.append(f"- {name} (due since {due_day})")
    return "\n".join(lines)


def _normalize_coaching_output(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if line.startswith("```"):
            continue

        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        numbered = re.match(r"^(\d+)\.\s+(.*)$", line)
        if numbered:
            line = f"{numbered.group(1)}) {numbered.group(2)}"

        line = line.replace("**", "").replace("__", "").replace("`", "").replace("*", "")

        if re.match(r"^\s*[-*]\s+", line):
            line = re.sub(r"^\s*[-*]\s+", "- ", line)
        elif re.match(r"^\s+\S", raw_line):
            line = raw_line.strip()

        cleaned_lines.append(line)

    normalized: list[str] = []
    last_blank = False
    for line in cleaned_lines:
        if not line:
            if not last_blank:
                normalized.append("")
            last_blank = True
            continue
        normalized.append(line)
        last_blank = False

    return "\n".join(normalized).strip()


def _build_due_chore_keyboard(due_chores: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for chore in due_chores:
        rows.append([InlineKeyboardButton(f"Done: {chore.get('name', '')}", callback_data=f"chore_done:{chore.get('_id')}")])
    return InlineKeyboardMarkup(rows)


async def chores_morning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = context.application.bot_data["store"]
    now = datetime.now(timezone.utc)
    if now.weekday() not in WEEKEND_DAYS:
        return

    for user_id in store.list_user_ids():
        try:
            store.ensure_default_chores(user_id)
            due_chores = store.list_due_chores(user_id=user_id, on_date=now.date())
            if not due_chores:
                continue

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Weekend chore reminder (morning)\n\n"
                    "Please complete and confirm these tasks today:\n"
                    f"{_format_due_rows(due_chores)}"
                ),
                reply_markup=_build_due_chore_keyboard(due_chores),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Morning chores reminder failed for user %s: %s", user_id, exc)


async def chores_eod_confirmation_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = context.application.bot_data["store"]
    now = datetime.now(timezone.utc)
    if now.weekday() not in WEEKEND_DAYS:
        return

    for user_id in store.list_user_ids():
        try:
            store.ensure_default_chores(user_id)
            due_chores = store.list_due_chores(user_id=user_id, on_date=now.date())
            if not due_chores:
                continue

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "End-of-day chore confirmation\n\n"
                    "Please confirm what is done before the day ends.\n"
                    "Anything not confirmed stays in weekend reminders.\n"
                    f"{_format_due_rows(due_chores)}"
                ),
                reply_markup=_build_due_chore_keyboard(due_chores),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("EOD chores confirmation failed for user %s: %s", user_id, exc)

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.prompts import (
    COACH_SYSTEM_PROMPT,
    build_checkin_prompt,
    build_improvement_prompt,
    fallback_coaching_message,
    fallback_improvement_message,
)


logger = logging.getLogger(__name__)
WEEKEND_DAYS = {5, 6}  # Saturday, Sunday
DAILY_REFLECTION_QUESTIONS = (
    {
        "key": "who_am_i",
        "text": "Answer the question on a daily basis for 5 min: Who am I?",
    },
    {
        "key": "lower_expectations",
        "text": "Need to work on lowering expectations so that I am happier.",
    },
)
_MOMENTUM_WORDS = {
    "done",
    "completed",
    "finished",
    "shipped",
    "sent",
    "called",
    "closed",
    "progress",
    "focused",
    "win",
}
_RESISTANCE_WORDS = {
    "stuck",
    "avoid",
    "avoiding",
    "procrast",
    "later",
    "tired",
    "blocked",
    "overwhelmed",
    "distracted",
    "hard",
    "cannot",
    "can't",
}
_MONEY_KEYWORDS = {
    "sales",
    "sell",
    "client",
    "lead",
    "prospect",
    "revenue",
    "invoice",
    "pricing",
    "offer",
    "proposal",
    "outreach",
    "contract",
    "funnel",
    "ads",
    "campaign",
    "market",
}
_WINDOWS = {
    "early_morning": (5, 8),
    "morning": (9, 11),
    "afternoon": (12, 16),
    "evening": (17, 21),
}


def generate_coaching_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, weekly: bool = False) -> str:
    store = context.application.bot_data["store"]
    settings = context.application.bot_data["settings"]
    ai = context.application.bot_data["ai"]

    profile = store.get_user_profile(user_id)
    main_goal = profile.get("main_goal", "make money")
    active_todos = store.list_active_todos(user_id, limit=30)
    completed_todos = store.get_recent_completed_todos(user_id, days=120, limit=300)
    stale_todos = store.get_stale_todos(user_id, stale_days=settings.stale_task_days, limit=10)
    overdue_todos = store.get_overdue_todos(user_id, limit=10)
    stats = store.get_stats(user_id)
    recent_notes = store.get_recent_journal_entries(user_id, limit=10)
    recent_reflections = store.get_recent_reflection_answers(user_id, limit=8)
    learning_profile = _build_learning_profile(
        active_todos=active_todos,
        completed_todos=completed_todos,
        recent_notes=recent_notes,
        recent_reflections=recent_reflections,
        stale_todos=stale_todos,
        overdue_todos=overdue_todos,
    )

    prompt = build_checkin_prompt(
        main_goal=main_goal,
        active_todos=active_todos,
        stale_todos=stale_todos,
        overdue_todos=overdue_todos,
        stats=stats,
        recent_notes=recent_notes,
        recent_reflections=recent_reflections,
        learning_profile=learning_profile,
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
            learning_profile=learning_profile,
        )
    )


def generate_improvement_message(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    store = context.application.bot_data["store"]
    ai = context.application.bot_data["ai"]

    profile = store.get_user_profile(user_id)
    main_goal = profile.get("main_goal", "make money")
    active_todos = store.list_active_todos(user_id, limit=40)
    completed_todos = store.get_recent_completed_todos(user_id, days=180, limit=400)
    stale_todos = store.get_stale_todos(user_id, stale_days=7, limit=20)
    overdue_todos = store.get_overdue_todos(user_id, limit=20)
    recent_notes = store.get_recent_journal_entries(user_id, limit=20)
    recent_reflections = store.get_recent_reflection_answers(user_id, limit=12)
    learning_profile = _build_learning_profile(
        active_todos=active_todos,
        completed_todos=completed_todos,
        recent_notes=recent_notes,
        recent_reflections=recent_reflections,
        stale_todos=stale_todos,
        overdue_todos=overdue_todos,
    )

    prompt = build_improvement_prompt(
        main_goal=main_goal,
        active_todos=active_todos,
        recent_notes=recent_notes,
        recent_reflections=recent_reflections,
        learning_profile=learning_profile,
    )
    ai_message = ai.generate(COACH_SYSTEM_PROMPT, prompt)
    if ai_message:
        return _normalize_coaching_output(ai_message)

    return _normalize_coaching_output(
        fallback_improvement_message(
            learning_profile=learning_profile,
            main_goal=main_goal,
        )
    )


async def daily_checkin_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for user_id in _target_user_ids(context):
        try:
            message = generate_coaching_message(context, user_id=user_id, weekly=False)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Daily Check-in\n\n{message}",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Daily check-in failed for user %s: %s", user_id, exc)


async def weekly_review_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for user_id in _target_user_ids(context):
        try:
            message = generate_coaching_message(context, user_id=user_id, weekly=True)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Weekly Review\n\n{message}",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Weekly review failed for user %s: %s", user_id, exc)


def _build_learning_profile(
    *,
    active_todos: list[dict[str, Any]],
    completed_todos: list[dict[str, Any]],
    recent_notes: list[str],
    recent_reflections: list[str],
    stale_todos: list[dict[str, Any]],
    overdue_todos: list[dict[str, Any]],
) -> dict[str, Any]:
    durations: list[float] = []
    project_type_durations: dict[str, list[float]] = {}
    completion_window_counts = {window: 0 for window in _WINDOWS}

    for todo in completed_todos:
        created = todo.get("created_at")
        completed = todo.get("completed_at")
        if created and completed:
            duration = max((completed - created).total_seconds() / 86400.0, 0.0)
            durations.append(duration)
            project_type = str(todo.get("project_type", "general"))
            project_type_durations.setdefault(project_type, []).append(duration)

        if completed:
            hour = int(completed.astimezone(timezone.utc).hour)
            for window, (start, end) in _WINDOWS.items():
                if start <= hour <= end:
                    completion_window_counts[window] += 1
                    break

    active_high = [todo for todo in active_todos if int(todo.get("priority", 2)) == 1]
    overdue_high = [todo for todo in overdue_todos if int(todo.get("priority", 2)) == 1]
    stale_high = [todo for todo in stale_todos if int(todo.get("priority", 2)) == 1]

    conflict_flags: list[str] = []
    if len(active_high) > 4:
        conflict_flags.append(f"too many high-priority tasks in parallel ({len(active_high)})")
    if overdue_high:
        conflict_flags.append(f"overdue high-priority tasks ({len(overdue_high)})")
    if len(stale_high) >= 2:
        conflict_flags.append(f"stale high-priority tasks ({len(stale_high)})")
    due_soon = _count_due_soon(active_todos, days=7)
    if due_soon >= 5:
        conflict_flags.append(f"deadline cluster in next 7 days ({due_soon} tasks)")

    momentum_signals, resistance_signals, willingness_score = _estimate_willingness(
        recent_notes + recent_reflections
    )
    money_ratio = _money_aligned_ratio(active_todos)

    project_type_breakdown_lines = []
    for project_type, values in sorted(
        project_type_durations.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        if not values:
            continue
        project_type_breakdown_lines.append(
            f"{project_type}: count={len(values)}, avg_days={mean(values):.1f}"
        )

    return {
        "completed_tasks_sample": len(completed_todos),
        "avg_completion_days": round(mean(durations), 1) if durations else None,
        "best_completion_window": _best_completion_window(completion_window_counts),
        "top_project_types": [
            project_type
            for project_type, values in sorted(
                project_type_durations.items(),
                key=lambda item: len(item[1]),
                reverse=True,
            )[:3]
        ],
        "project_type_breakdown_lines": project_type_breakdown_lines,
        "willingness_score": willingness_score,
        "momentum_signals": momentum_signals,
        "resistance_signals": resistance_signals,
        "money_aligned_active_ratio": round(money_ratio, 2),
        "conflict_flags": conflict_flags,
    }


def _count_due_soon(active_todos: list[dict[str, Any]], days: int) -> int:
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(days=days)
    count = 0
    for todo in active_todos:
        deadline = todo.get("deadline")
        if deadline and now <= deadline <= threshold:
            count += 1
    return count


def _best_completion_window(counts: dict[str, int]) -> str:
    best = max(counts.items(), key=lambda item: item[1], default=("n/a", 0))
    return best[0] if best[1] > 0 else "n/a"


def _estimate_willingness(recent_notes: list[str]) -> tuple[int, int, int]:
    momentum = 0
    resistance = 0
    for note in recent_notes:
        text = note.lower()
        for word in _MOMENTUM_WORDS:
            if word in text:
                momentum += 1
        for word in _RESISTANCE_WORDS:
            if word in text:
                resistance += 1

    raw_score = 3 + (momentum - resistance) * 0.2
    willingness = int(max(1, min(5, round(raw_score))))
    return momentum, resistance, willingness


def _money_aligned_ratio(active_todos: list[dict[str, Any]]) -> float:
    if not active_todos:
        return 0.0
    aligned = 0
    for todo in active_todos:
        title = str(todo.get("title", "")).lower()
        project_type = str(todo.get("project_type", ""))
        if any(keyword in title for keyword in _MONEY_KEYWORDS) or project_type in {"sales", "marketing", "product"}:
            aligned += 1
    return aligned / len(active_todos)


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


def _target_user_ids(context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    store = context.application.bot_data["store"]
    settings = context.application.bot_data["settings"]
    if settings.allowed_chat_id is not None:
        return [settings.allowed_chat_id]
    return store.list_user_ids()


def _build_chore_action_keyboard(chore_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Done", callback_data=f"chore_done:{chore_id}"),
                InlineKeyboardButton("Not done", callback_data=f"chore_not_done:{chore_id}"),
            ],
            [InlineKeyboardButton("Pass weekend", callback_data=f"chore_pass_weekend:{chore_id}")],
        ]
    )


async def chores_morning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = context.application.bot_data["store"]
    now = datetime.now(timezone.utc)
    if now.weekday() not in WEEKEND_DAYS:
        return

    for user_id in _target_user_ids(context):
        try:
            store.ensure_default_chores(user_id)
            due_chores = store.list_due_chores(user_id=user_id, on_date=now.date())
            if not due_chores:
                continue

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Weekend chore reminder (morning)\n\n"
                    "Please answer each chore one by one."
                ),
            )
            for chore in due_chores:
                chore_id = str(chore.get("_id"))
                name = str(chore.get("name", ""))
                due_day = "n/a"
                next_due = chore.get("next_due_date")
                if next_due:
                    due_day = next_due.astimezone(timezone.utc).strftime("%Y-%m-%d")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"{name}\nDue since: {due_day}\n\nDone today?",
                    reply_markup=_build_chore_action_keyboard(chore_id),
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Morning chores reminder failed for user %s: %s", user_id, exc)


async def chores_eod_confirmation_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = context.application.bot_data["store"]
    now = datetime.now(timezone.utc)
    if now.weekday() not in WEEKEND_DAYS:
        return

    for user_id in _target_user_ids(context):
        try:
            store.ensure_default_chores(user_id)
            due_chores = store.list_due_chores(user_id=user_id, on_date=now.date())
            if not due_chores:
                continue

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "End-of-day chore confirmation\n\n"
                    "Please confirm each chore.\n"
                    "Anything not done stays in weekend reminders."
                ),
            )
            for chore in due_chores:
                chore_id = str(chore.get("_id"))
                name = str(chore.get("name", ""))
                due_day = "n/a"
                next_due = chore.get("next_due_date")
                if next_due:
                    due_day = next_due.astimezone(timezone.utc).strftime("%Y-%m-%d")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"{name}\nDue since: {due_day}\n\nDone today?",
                    reply_markup=_build_chore_action_keyboard(chore_id),
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("EOD chores confirmation failed for user %s: %s", user_id, exc)


async def daily_reflection_question_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = context.application.bot_data["store"]
    now = datetime.now(timezone.utc)

    for user_id in _target_user_ids(context):
        try:
            for question in DAILY_REFLECTION_QUESTIONS:
                created = store.ensure_daily_reflection_prompt(
                    user_id=user_id,
                    question_key=question["key"],
                    question=question["text"],
                    asked_at=now,
                )
                if not created:
                    continue

                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "Daily Reflection (5 min)\n\n"
                        f"{question['text']}\n\n"
                        "Reply with your answer. I will store it for future analysis.\n"
                        "If you're not motivated today, send /pass."
                    ),
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Daily reflection prompt failed for user %s: %s", user_id, exc)

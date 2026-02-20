from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.jobs import DAILY_REFLECTION_QUESTIONS, generate_coaching_message, generate_improvement_message
from bot.utils import (
    ParsedAddPayload,
    format_deadline,
    infer_project_type,
    parse_add_payload,
    parse_deadline,
    parse_priority,
    priority_to_label,
)

ADD_TITLE, ADD_PRIORITY, ADD_DEADLINE = range(3)
HELP_TEXT = (
    "Commands:\n"
    "/start - initialize profile and show overview\n"
    "/help - show this help\n"
    "/add - interactive add flow\n"
    "/add <task> | <priority> | <deadline YYYY-MM-DD> - quick add\n"
    "/list - show active tasks with Done/Delete buttons\n"
    "/goal - show current main goal\n"
    "/goal <text> - update main goal\n"
    "/checkin - run daily-style coaching now\n"
    "/review - run weekly-style coaching now\n"
    "/improve - analyze your execution patterns and improvements\n"
    "/reflect - ask today's reflection questions\n"
    "/pass - skip today's pending reflection\n"
    "/chores - view recurring weekend chores\n"
    "/cancel - cancel the /add interactive flow\n\n"
    "Priority: high/medium/low or p1/p2/p3 or 1/2/3.\n"
    "Deadline: YYYY-MM-DD, or skip/none (defaults to +1 month).\n"
    "Tip: send non-command text as accomplishment/blocker notes for smarter coaching."
)


def _format_utc_date(value: Optional[datetime]) -> str:
    if not value:
        return "n/a"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _get_allowed_chat_id(context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    settings = context.application.bot_data["settings"]
    return settings.allowed_chat_id


def _is_authorized_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed_chat_id = _get_allowed_chat_id(context)
    if allowed_chat_id is None:
        return True
    if not update.effective_chat:
        return False
    return update.effective_chat.id == allowed_chat_id


async def _deny_unauthorized(update: Update) -> None:
    if update.callback_query:
        await update.callback_query.answer("Unauthorized chat.", show_alert=True)
        return
    if update.effective_message:
        await update.effective_message.reply_text("Unauthorized chat.")


async def _authorize_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if _is_authorized_chat(update, context):
        return True
    await _deny_unauthorized(update)
    return False


def _todo_message(todo: dict, index: int) -> str:
    todo_id = str(todo.get("_id"))
    added_date = _format_utc_date(todo.get("created_at"))
    project_type = str(todo.get("project_type") or infer_project_type(str(todo.get("title", ""))))
    return (
        f"[{index}] {todo.get('title')}\n"
        f"Type: {project_type}\n"
        f"Priority: {priority_to_label(int(todo.get('priority', 2)))}\n"
        f"Deadline: {format_deadline(todo.get('deadline'))}\n"
        f"Added: {added_date}\n"
        f"Task ID: {todo_id}"
    )


def _save_parsed_todo(context: ContextTypes.DEFAULT_TYPE, user_id: int, parsed: ParsedAddPayload) -> dict:
    store = context.application.bot_data["store"]
    return store.add_todo(
        user_id=user_id,
        title=parsed.title,
        priority=parsed.priority,
        deadline=parsed.deadline,
    )


def _ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    if not update.effective_user:
        return None
    store = context.application.bot_data["store"]
    user = update.effective_user
    store.upsert_user(user_id=user.id, username=user.username or "", first_name=user.first_name or "")
    return user.id


def _build_chore_done_keyboard(chore_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Done", callback_data=f"chore_done:{chore_id}")]]
    )


def _build_reflection_prompt_text(question: str) -> str:
    return (
        "Daily Reflection (5 min)\n\n"
        f"{question}\n\n"
        "Reply with your answer. I will store it for future analysis.\n"
        "If you're not motivated today, send /pass."
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    _ensure_user(update, context)
    await update.effective_message.reply_text(
        "To-Do Coach is active.\n\n"
        + HELP_TEXT
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    await update.effective_message.reply_text(HELP_TEXT)


async def goal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    store = context.application.bot_data["store"]
    user_id = _ensure_user(update, context)
    if user_id is None:
        return

    if context.args:
        new_goal = " ".join(context.args).strip()
        if not new_goal:
            await update.effective_message.reply_text("Goal cannot be empty.")
            return
        store.set_main_goal(user_id, new_goal)
        await update.effective_message.reply_text(f"Main goal updated: {new_goal}")
        return

    profile = store.get_user_profile(user_id)
    goal = profile.get("main_goal", "make money")
    await update.effective_message.reply_text(f"Current main goal: {goal}")


async def add_entry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or not update.effective_message:
        return ConversationHandler.END
    if not await _authorize_chat(update, context):
        return ConversationHandler.END
    user_id = _ensure_user(update, context)
    if user_id is None:
        return ConversationHandler.END

    if context.args:
        raw_payload = " ".join(context.args).strip()
        parsed, error = parse_add_payload(raw_payload)
        if error:
            await update.effective_message.reply_text(f"{error}\nExample: /add Call lead | high | 2026-03-01")
            return ConversationHandler.END

        saved = _save_parsed_todo(context, user_id=user_id, parsed=parsed)
        await update.effective_message.reply_text(
            f"Added: {saved.get('title')} | priority {priority_to_label(saved.get('priority', 2))} | deadline {format_deadline(saved.get('deadline'))}"
        )
        return ConversationHandler.END

    context.user_data["add_task"] = {}
    await update.effective_message.reply_text("Send task title.")
    return ADD_TITLE


async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message:
        return ConversationHandler.END
    if not await _authorize_chat(update, context):
        return ConversationHandler.END
    title = update.effective_message.text.strip()
    if not title:
        await update.effective_message.reply_text("Title cannot be empty. Send task title.")
        return ADD_TITLE

    context.user_data["add_task"] = {"title": title}
    await update.effective_message.reply_text("Send priority: high/medium/low (or 1/2/3).")
    return ADD_PRIORITY


async def add_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_message:
        return ConversationHandler.END
    if not await _authorize_chat(update, context):
        return ConversationHandler.END
    priority_raw = update.effective_message.text.strip()
    priority = parse_priority(priority_raw)
    if priority is None:
        await update.effective_message.reply_text("Invalid priority. Use high/medium/low or 1/2/3.")
        return ADD_PRIORITY

    context.user_data.setdefault("add_task", {})["priority"] = priority
    await update.effective_message.reply_text(
        "Send deadline in YYYY-MM-DD, or `skip` for default (+1 month).",
        parse_mode="Markdown",
    )
    return ADD_DEADLINE


async def add_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or not update.effective_message:
        return ConversationHandler.END
    if not await _authorize_chat(update, context):
        return ConversationHandler.END
    deadline_raw = update.effective_message.text.strip()
    deadline, error = parse_deadline(deadline_raw)
    if error:
        await update.effective_message.reply_text(error)
        return ADD_DEADLINE

    draft = context.user_data.get("add_task", {})
    title = draft.get("title", "").strip()
    priority = int(draft.get("priority", 2))
    if not title:
        await update.effective_message.reply_text("Task title missing. Start again with /add.")
        return ConversationHandler.END

    parsed = ParsedAddPayload(title=title, priority=priority, deadline=deadline)
    saved = _save_parsed_todo(context, user_id=update.effective_user.id, parsed=parsed)
    context.user_data.pop("add_task", None)
    await update.effective_message.reply_text(
        f"Added: {saved.get('title')} | priority {priority_to_label(priority)} | deadline {format_deadline(deadline)}"
    )
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorize_chat(update, context):
        return ConversationHandler.END
    if update.effective_message:
        await update.effective_message.reply_text("Add flow canceled.")
    context.user_data.pop("add_task", None)
    return ConversationHandler.END


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    store = context.application.bot_data["store"]
    user_id = _ensure_user(update, context)
    if user_id is None:
        return
    todos = store.list_active_todos(user_id=user_id, limit=30)
    if not todos:
        await update.effective_message.reply_text("No active tasks.")
        return

    await update.effective_message.reply_text(
        "Active tasks. Use each task's buttons to mark done or delete."
    )
    for index, todo in enumerate(todos, start=1):
        todo_id = str(todo.get("_id"))
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Done", callback_data=f"done:{todo_id}"),
                    InlineKeyboardButton("Delete", callback_data=f"delete:{todo_id}"),
                ]
            ]
        )
        await update.effective_message.reply_text(
            _todo_message(todo, index=index),
            reply_markup=keyboard,
        )


async def chores_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    store = context.application.bot_data["store"]
    user_id = _ensure_user(update, context)
    if user_id is None:
        return

    due_chores = store.list_due_chores(user_id=user_id)
    if due_chores:
        await update.effective_message.reply_text(
            "Weekend chores pending confirmation. Mark each one when done:"
        )
        for chore in due_chores:
            chore_id = str(chore.get("_id"))
            name = chore.get("name", "")
            next_due = _format_utc_date(chore.get("next_due_date"))
            await update.effective_message.reply_text(
                f"{name}\nDue since: {next_due}",
                reply_markup=_build_chore_done_keyboard(chore_id),
            )
        return

    all_chores = store.list_chores(user_id=user_id)
    if not all_chores:
        await update.effective_message.reply_text("No recurring chores configured.")
        return

    lines = ["No overdue chores right now. Upcoming schedule:"]
    for chore in all_chores:
        name = chore.get("name", "")
        interval = int(chore.get("interval_days", 0))
        next_due = _format_utc_date(chore.get("next_due_date"))
        lines.append(f"- {name}: every {interval} day(s), next due {next_due}")
    await update.effective_message.reply_text("\n".join(lines))


async def todo_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.effective_user:
        return
    if not await _authorize_chat(update, context):
        return
    query = update.callback_query
    await query.answer()
    if not query.message or not query.message.text:
        return

    raw = query.data or ""
    if ":" not in raw:
        return
    action, todo_id = raw.split(":", maxsplit=1)
    store = context.application.bot_data["store"]
    user_id = update.effective_user.id

    if action == "done":
        ok = store.mark_todo_done(user_id=user_id, todo_id=todo_id)
        if ok:
            await query.edit_message_text(f"{query.message.text}\n\nStatus: completed.")
        else:
            await query.edit_message_text(f"{query.message.text}\n\nStatus: not found/already updated.")
        return

    if action == "delete":
        ok = store.delete_todo(user_id=user_id, todo_id=todo_id)
        if ok:
            await query.edit_message_text(f"{query.message.text}\n\nStatus: deleted.")
        else:
            await query.edit_message_text(f"{query.message.text}\n\nStatus: not found/already updated.")
        return

    if action == "chore_done":
        updated = store.mark_chore_done(user_id=user_id, chore_id=todo_id)
        if updated:
            next_due = _format_utc_date(updated.get("next_due_date"))
            await query.edit_message_text(f"{query.message.text}\n\nStatus: confirmed done. Next due: {next_due}.")
        else:
            await query.edit_message_text(f"{query.message.text}\n\nStatus: not found/already updated.")


async def checkin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    _ensure_user(update, context)
    message = generate_coaching_message(context, user_id=update.effective_user.id, weekly=False)
    await update.effective_message.reply_text(message)


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    _ensure_user(update, context)
    message = generate_coaching_message(context, user_id=update.effective_user.id, weekly=True)
    await update.effective_message.reply_text(message)


async def improve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    _ensure_user(update, context)
    message = generate_improvement_message(context, user_id=update.effective_user.id)
    await update.effective_message.reply_text(message)


async def reflect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    store = context.application.bot_data["store"]
    user_id = _ensure_user(update, context)
    if user_id is None:
        return

    created_questions: list[str] = []
    for question in DAILY_REFLECTION_QUESTIONS:
        created = store.ensure_daily_reflection_prompt(
            user_id=user_id,
            question_key=question["key"],
            question=question["text"],
        )
        if created:
            created_questions.append(question["text"])

    if created_questions:
        for question_text in created_questions:
            await update.effective_message.reply_text(_build_reflection_prompt_text(question_text))
        return

    pending = store.get_pending_reflection(user_id)
    if pending:
        remaining = store.count_pending_reflections(user_id=user_id)
        suffix = f"\n\nPending reflections: {remaining}" if remaining > 1 else ""
        await update.effective_message.reply_text(
            _build_reflection_prompt_text(str(pending.get("question", "Who am I?"))) + suffix
        )
        return

    await update.effective_message.reply_text("Today's reflection questions are already answered or skipped.")


async def pass_reflection_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not await _authorize_chat(update, context):
        return
    store = context.application.bot_data["store"]
    user_id = _ensure_user(update, context)
    if user_id is None:
        return

    pending = store.get_pending_reflection(user_id=user_id)
    if not pending:
        await update.effective_message.reply_text("No pending reflection to skip right now.")
        return

    if store.pass_pending_reflection(user_id=user_id, skip_note="pass_command"):
        question = str(pending.get("question", "Reflection question"))
        remaining = store.count_pending_reflections(user_id=user_id)
        await update.effective_message.reply_text(f"Skipped: {question}")
        if remaining > 0:
            next_pending = store.get_pending_reflection(user_id=user_id)
            if next_pending:
                await update.effective_message.reply_text(
                    _build_reflection_prompt_text(str(next_pending.get("question", "Who am I?")))
                    + f"\n\nPending reflections: {remaining}"
                )
        return
    await update.effective_message.reply_text("Could not skip reflection right now.")


async def capture_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message or not update.effective_message.text:
        return
    if not await _authorize_chat(update, context):
        return
    text = update.effective_message.text.strip()
    if not text:
        return
    store = context.application.bot_data["store"]
    user_id = update.effective_user.id
    pending_before = store.get_pending_reflection(user_id=user_id)

    lowered = text.lower()
    if lowered in {"pass", "skip", "/pass"}:
        if store.pass_pending_reflection(user_id=user_id, skip_note=lowered):
            remaining = store.count_pending_reflections(user_id=user_id)
            await update.effective_message.reply_text("Reflection skipped for today.")
            if remaining > 0:
                next_pending = store.get_pending_reflection(user_id=user_id)
                if next_pending:
                    await update.effective_message.reply_text(
                        _build_reflection_prompt_text(str(next_pending.get("question", "Who am I?")))
                        + f"\n\nPending reflections: {remaining}"
                    )
            return

    if store.save_pending_reflection_answer(user_id=user_id, answer=text):
        question_text = str((pending_before or {}).get("question") or "Reflection")
        store.add_journal_entry(
            user_id=user_id,
            text=f"{question_text} -> {text}",
            source="reflection",
        )
        remaining = store.count_pending_reflections(user_id=user_id)
        await update.effective_message.reply_text("Saved your daily reflection.")
        if remaining > 0:
            next_pending = store.get_pending_reflection(user_id=user_id)
            if next_pending:
                await update.effective_message.reply_text(
                    _build_reflection_prompt_text(str(next_pending.get("question", "Who am I?")))
                    + f"\n\nPending reflections: {remaining}"
                )
        return

    store.add_journal_entry(user_id=user_id, text=text, source="chat")


def build_handlers() -> list:
    add_conversation = ConversationHandler(
        entry_points=[CommandHandler("add", add_entry_command)],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            ADD_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_priority)],
            ADD_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_deadline)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        allow_reentry=True,
    )

    return [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        CommandHandler("goal", goal_command),
        add_conversation,
        CommandHandler("list", list_command),
        CommandHandler("chores", chores_command),
        CommandHandler("checkin", checkin_command),
        CommandHandler("review", review_command),
        CommandHandler("improve", improve_command),
        CommandHandler("reflect", reflect_command),
        CommandHandler("pass", pass_reflection_command),
        CallbackQueryHandler(todo_action_callback, pattern=r"^(done|delete|chore_done):"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, capture_notes),
    ]

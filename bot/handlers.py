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

from bot.jobs import generate_coaching_message
from bot.utils import ParsedAddPayload, format_deadline, parse_add_payload, parse_deadline, parse_priority, priority_to_label

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


def _todo_message(todo: dict, index: int) -> str:
    todo_id = str(todo.get("_id"))
    added_date = _format_utc_date(todo.get("created_at"))
    return (
        f"[{index}] {todo.get('title')}\n"
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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    _ensure_user(update, context)
    await update.effective_message.reply_text(
        "To-Do Coach is active.\n\n"
        + HELP_TEXT
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(HELP_TEXT)


async def goal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
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
    if update.effective_message:
        await update.effective_message.reply_text("Add flow canceled.")
    context.user_data.pop("add_task", None)
    return ConversationHandler.END


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
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
    _ensure_user(update, context)
    message = generate_coaching_message(context, user_id=update.effective_user.id, weekly=False)
    await update.effective_message.reply_text(message)


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    _ensure_user(update, context)
    message = generate_coaching_message(context, user_id=update.effective_user.id, weekly=True)
    await update.effective_message.reply_text(message)


async def capture_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message or not update.effective_message.text:
        return
    text = update.effective_message.text.strip()
    if not text:
        return
    store = context.application.bot_data["store"]
    store.add_journal_entry(user_id=update.effective_user.id, text=text, source="chat")


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
        CallbackQueryHandler(todo_action_callback, pattern=r"^(done|delete|chore_done):"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, capture_notes),
    ]

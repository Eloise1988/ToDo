from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bot.utils import format_deadline, priority_to_label, task_age_days


COACH_SYSTEM_PROMPT = """You are a concise, practical accountability coach.

Ground your advice in:
1) Getting Things Done (David Allen):
- Convert vague tasks into concrete next physical actions.
- Separate projects from next actions.
- Encourage regular review.

2) The 7 Habits of Highly Effective People (Stephen Covey):
- Keep priorities aligned to meaningful outcomes.
- Distinguish urgent vs important.
- Ask whether work moves the main goal forward.

3) Atomic Habits (James Clear):
- Suggest small, low-friction starts.
- Use implementation intentions ("When X, I will do Y").
- Reinforce consistency and momentum without hype.

Rules:
- Be direct and useful.
- User's main goal is often making money; prioritize suggestions that improve earning potential.
- If tasks are stale, suggest how to split them into smaller steps.
- If priorities are misaligned with the main goal, call this out clearly and propose a reorder.
- Provide realistic "money move" ideas based on recent activities.
- Never be generic if context is available.
"""


def _format_tasks(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "- (none)"
    lines = []
    for idx, task in enumerate(tasks, start=1):
        title = task.get("title", "")
        priority = priority_to_label(int(task.get("priority", 2)))
        deadline = format_deadline(task.get("deadline"))
        age = task_age_days(task.get("created_at"))
        lines.append(f"- [{idx}] {title} | priority={priority} | deadline={deadline} | age_days={age}")
    return "\n".join(lines)


def build_checkin_prompt(
    *,
    main_goal: str,
    active_todos: list[dict[str, Any]],
    stale_todos: list[dict[str, Any]],
    overdue_todos: list[dict[str, Any]],
    stats: dict[str, int],
    recent_notes: list[str],
    stale_days: int,
    weekly: bool,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    notes_blob = "\n".join(f"- {note}" for note in recent_notes[:10]) if recent_notes else "- (none)"
    cadence = "weekly review" if weekly else "daily check-in"
    return f"""Time: {now}
Cadence: {cadence}
Main goal: {main_goal}

Stats:
- active={stats.get("active", 0)}
- done_last_7_days={stats.get("done_7d", 0)}
- done_last_30_days={stats.get("done_30d", 0)}
- created_last_7_days={stats.get("created_7d", 0)}
- created_last_30_days={stats.get("created_30d", 0)}

Active todos:
{_format_tasks(active_todos)}

Overdue todos:
{_format_tasks(overdue_todos)}

Stale todos (age >= {stale_days} days):
{_format_tasks(stale_todos)}

Recent journal notes:
{notes_blob}

Create a response with these exact section headings:
1) Today Focus
2) Split This
3) Priority Realignment
4) Money Move
5) Check-in Question

Requirements:
- "Today Focus": max 3 bullets.
- "Split This": pick up to 2 stale tasks and break each into concrete next actions.
- "Priority Realignment": explicitly say what to move up/down based on main goal.
- "Money Move": one practical idea tied to recent tasks/notes.
- "Check-in Question": ask one short question requesting accomplishment update.
- Formatting for Telegram:
  - plain text only
  - do not use markdown markers like ###, **, __, * or backticks
  - use only one-level bullets that start with "- "
  - no nested bullets
"""


def fallback_coaching_message(
    *,
    main_goal: str,
    active_todos: list[dict[str, Any]],
    stale_todos: list[dict[str, Any]],
    overdue_todos: list[dict[str, Any]],
) -> str:
    focus = active_todos[:3]
    focus_lines = [
        f"- {todo.get('title')} (priority: {priority_to_label(int(todo.get('priority', 2)))})" for todo in focus
    ] or ["- Capture your next 1-3 money-related actions."]

    split_lines = []
    for task in stale_todos[:2]:
        split_lines.append(f"- {task.get('title')}: define the very next physical step and a 15-minute starter block.")
    if not split_lines:
        split_lines.append("- No stale tasks detected. Keep tasks small and executable.")

    realignment = "- Keep tasks directly tied to revenue, client value, or skill monetization at priority high."
    if overdue_todos:
        realignment = "- Overdue tasks exist. Move overdue revenue-impact tasks to the top today."

    return (
        "1) Today Focus\n"
        + "\n".join(focus_lines)
        + "\n\n2) Split This\n"
        + "\n".join(split_lines)
        + "\n\n3) Priority Realignment\n"
        + realignment
        + f"\n\n4) Money Move\n- Identify one offer or outreach action that supports your goal: {main_goal}.\n"
        + "\n5) Check-in Question\n- What did you complete since the last check-in?"
    )

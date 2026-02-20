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


def _format_learning_profile(profile: dict[str, Any]) -> str:
    if not profile:
        return "- (not enough history yet)"

    top_types = ", ".join(profile.get("top_project_types", [])[:3]) or "n/a"
    avg_days = profile.get("avg_completion_days")
    avg_days_display = f"{avg_days:.1f}" if isinstance(avg_days, (int, float)) else "n/a"

    lines = [
        f"- completed_tasks_sample={profile.get('completed_tasks_sample', 0)}",
        f"- avg_completion_days={avg_days_display}",
        f"- willingness_score_1_to_5={profile.get('willingness_score', 3)}",
        f"- resistance_signals={profile.get('resistance_signals', 0)}",
        f"- momentum_signals={profile.get('momentum_signals', 0)}",
        f"- top_project_types={top_types}",
        f"- best_completion_window={profile.get('best_completion_window', 'n/a')}",
        f"- money_aligned_active_ratio={profile.get('money_aligned_active_ratio', 0):.2f}",
        f"- conflict_flags={'; '.join(profile.get('conflict_flags', [])) or 'none'}",
    ]
    type_lines = profile.get("project_type_breakdown_lines", [])
    if type_lines:
        lines.append("- project_type_breakdown:")
        lines.extend(f"  - {line}" for line in type_lines[:6])
    return "\n".join(lines)


def build_checkin_prompt(
    *,
    main_goal: str,
    active_todos: list[dict[str, Any]],
    stale_todos: list[dict[str, Any]],
    overdue_todos: list[dict[str, Any]],
    stats: dict[str, int],
    recent_notes: list[str],
    recent_reflections: list[str],
    learning_profile: dict[str, Any],
    stale_days: int,
    weekly: bool,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    notes_blob = "\n".join(f"- {note}" for note in recent_notes[:10]) if recent_notes else "- (none)"
    reflections_blob = (
        "\n".join(f"- {answer}" for answer in recent_reflections[:6]) if recent_reflections else "- (none)"
    )
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

Recent "Who am I?" reflections:
{reflections_blob}

Execution learning profile:
{_format_learning_profile(learning_profile)}

Create a response with these exact section headings:
1) Today Focus
2) Split This
3) Priority Realignment
4) Money Move
5) Check-in Question
6) Process Improvement

Requirements:
- "Today Focus": max 3 bullets.
- "Split This": pick up to 2 stale tasks and break each into concrete next actions.
- "Priority Realignment": explicitly say what to move up/down based on main goal.
- "Money Move": one practical idea tied to recent tasks/notes.
- "Check-in Question": ask one short question requesting accomplishment update.
- "Process Improvement": give 2 specific adjustments based on how this user actually executes.
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
    learning_profile: dict[str, Any],
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

    process_improvement = [
        f"- Average completion time: {learning_profile.get('avg_completion_days', 'n/a')} day(s).",
        "- Timebox one high-value task today before low-impact admin work.",
    ]
    for flag in learning_profile.get("conflict_flags", [])[:1]:
        process_improvement.append(f"- Resolve conflict: {flag}.")

    return (
        "1) Today Focus\n"
        + "\n".join(focus_lines)
        + "\n\n2) Split This\n"
        + "\n".join(split_lines)
        + "\n\n3) Priority Realignment\n"
        + realignment
        + f"\n\n4) Money Move\n- Identify one offer or outreach action that supports your goal: {main_goal}.\n"
        + "\n5) Check-in Question\n- What did you complete since the last check-in?"
        + "\n\n6) Process Improvement\n"
        + "\n".join(process_improvement)
    )


def build_improvement_prompt(
    *,
    main_goal: str,
    active_todos: list[dict[str, Any]],
    recent_notes: list[str],
    recent_reflections: list[str],
    learning_profile: dict[str, Any],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    notes_blob = "\n".join(f"- {note}" for note in recent_notes[:12]) if recent_notes else "- (none)"
    reflections_blob = (
        "\n".join(f"- {answer}" for answer in recent_reflections[:10]) if recent_reflections else "- (none)"
    )
    return f"""Time: {now}
Main goal: {main_goal}

Active todos:
{_format_tasks(active_todos)}

Recent journal notes:
{notes_blob}

Recent "Who am I?" reflections:
{reflections_blob}

Execution learning profile:
{_format_learning_profile(learning_profile)}

Create a response with these exact section headings:
1) How You Get Things Done
2) Time-To-Done Pattern
3) Willingness and Friction
4) Project-Type Fit
5) Conflicts
6) What To Improve
7) AI Improvements
8) Next Experiment

Requirements:
- Be concrete and diagnostic, not generic.
- In "What To Improve", provide exactly 5 actions.
- In "AI Improvements", provide exactly 3 ways the bot can help better.
- "Next Experiment" must be a 7-day experiment with simple tracking.
- Formatting for Telegram:
  - plain text only
  - do not use markdown markers like ###, **, __, * or backticks
  - use only one-level bullets that start with "- "
  - no nested bullets
"""


def fallback_improvement_message(*, learning_profile: dict[str, Any], main_goal: str) -> str:
    avg_days = learning_profile.get("avg_completion_days", "n/a")
    best_window = learning_profile.get("best_completion_window", "n/a")
    top_types = ", ".join(learning_profile.get("top_project_types", [])[:3]) or "n/a"
    conflicts = learning_profile.get("conflict_flags", []) or ["too many parallel priorities"]
    willingness = learning_profile.get("willingness_score", 3)

    return (
        "1) How You Get Things Done\n"
        f"- You execute best during: {best_window}.\n"
        f"- Your dominant project types: {top_types}.\n"
        "\n2) Time-To-Done Pattern\n"
        f"- Average time to completion: {avg_days} day(s).\n"
        "- Fast wins exist when tasks are small and concrete.\n"
        "\n3) Willingness and Friction\n"
        f"- Estimated willingness score: {willingness}/5.\n"
        "- Reduce friction by defining one next physical action per task.\n"
        "\n4) Project-Type Fit\n"
        f"- Keep more active tasks linked to goal: {main_goal}.\n"
        "- Move low-leverage admin work after revenue tasks.\n"
        "\n5) Conflicts\n"
        + "\n".join(f"- {flag}" for flag in conflicts[:3])
        + "\n\n6) What To Improve\n"
        "- Limit active high-priority tasks to 3.\n"
        "- Timebox one 45-minute revenue task first each day.\n"
        "- Break any task older than 7 days into 2-3 steps.\n"
        "- Do a quick end-of-day review and mark completions.\n"
        "- Batch low-value admin work into one small block.\n"
        "\n7) AI Improvements\n"
        "- Ask the bot to propose next actions for stale tasks.\n"
        "- Ask the bot to re-rank tasks by money impact every weekend.\n"
        "- Ask the bot for a daily execution plan in your best work window.\n"
        "\n8) Next Experiment\n"
        "- For 7 days: do one revenue-first block daily and report done/not done each evening."
    )

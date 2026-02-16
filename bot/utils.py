from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Optional


PRIORITY_LABELS = {
    1: "High",
    2: "Medium",
    3: "Low",
}

_PRIORITY_ALIASES = {
    "1": 1,
    "p1": 1,
    "high": 1,
    "urgent": 1,
    "2": 2,
    "p2": 2,
    "medium": 2,
    "med": 2,
    "3": 3,
    "p3": 3,
    "low": 3,
}

_DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_PRIORITY_PATTERN = re.compile(r"\b(p[123]|high|medium|med|low|urgent|[123])\b", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedAddPayload:
    title: str
    priority: int
    deadline: Optional[datetime]


def priority_to_label(priority: int) -> str:
    return PRIORITY_LABELS.get(priority, "Medium")


def parse_priority(raw: str) -> Optional[int]:
    value = raw.strip().lower()
    return _PRIORITY_ALIASES.get(value)


def parse_deadline(raw: str) -> tuple[Optional[datetime], Optional[str]]:
    value = raw.strip().lower()
    if not value or value in {"skip", "none", "-"}:
        return None, None
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        return None, "Deadline must be in YYYY-MM-DD format, or use `skip`."
    # Store end-of-day UTC so due date remains active during that calendar day.
    return datetime.combine(parsed_date, time(23, 59, 59, tzinfo=timezone.utc)), None


def parse_add_payload(raw: str) -> tuple[Optional[ParsedAddPayload], Optional[str]]:
    payload = raw.strip()
    if not payload:
        return None, "Empty task. Use: /add Task | high | 2026-03-01"

    if "|" in payload:
        parts = [part.strip() for part in payload.split("|")]
        while len(parts) < 3:
            parts.append("")
        title, priority_raw, deadline_raw = parts[:3]
        if not title:
            return None, "Task title is required."
        priority = parse_priority(priority_raw) if priority_raw else 2
        if priority_raw and priority is None:
            return None, "Priority must be high/medium/low, p1/p2/p3, or 1/2/3."
        deadline, deadline_error = parse_deadline(deadline_raw)
        if deadline_error:
            return None, deadline_error
        return ParsedAddPayload(title=title, priority=priority or 2, deadline=deadline), None

    working = payload
    parsed_priority = 2

    date_match = _DATE_PATTERN.search(working)
    parsed_deadline = None
    if date_match:
        parsed_deadline, deadline_error = parse_deadline(date_match.group(1))
        if deadline_error:
            return None, deadline_error
        working = _DATE_PATTERN.sub("", working, count=1).strip()

    prio_match = _PRIORITY_PATTERN.search(working)
    if prio_match:
        maybe_priority = parse_priority(prio_match.group(1))
        if maybe_priority is not None:
            parsed_priority = maybe_priority
            working = _PRIORITY_PATTERN.sub("", working, count=1).strip()

    title = " ".join(working.split())
    if not title:
        return None, "Task title is required."

    return ParsedAddPayload(title=title, priority=parsed_priority, deadline=parsed_deadline), None


def format_deadline(deadline: Optional[datetime]) -> str:
    if not deadline:
        return "No deadline"
    return deadline.astimezone(timezone.utc).strftime("%Y-%m-%d")


def task_age_days(created_at: Optional[datetime]) -> int:
    if not created_at:
        return 0
    now = datetime.now(timezone.utc)
    return max(0, (now - created_at).days)

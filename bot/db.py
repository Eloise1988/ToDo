from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING, MongoClient

from bot.utils import infer_project_type


MAX_AWARE_DT = datetime(9999, 12, 31, tzinfo=timezone.utc)
LEGACY_COMBINED_CHORE_NAME = "Clean bedroom and bathroom"
DEFAULT_WEEKEND_CHORES = (
    {
        "name": "Water plants",
        "interval_days": 7,
        "preferred_weekday": 5,  # Saturday
    },
    {
        "name": "Clean sheets",
        "interval_days": 21,
        "preferred_weekday": 5,  # Saturday
    },
    {
        "name": "Clean bedroom",
        "interval_days": 30,
        "preferred_weekday": 5,  # Saturday
    },
    {
        "name": "Clean bathroom",
        "interval_days": 30,
        "preferred_weekday": 5,  # Saturday
    },
)


class MongoStore:
    def __init__(self, uri: str, db_name: str) -> None:
        self.client = MongoClient(uri, tz_aware=True)
        self.db = self.client[db_name]
        self.users = self.db.users
        self.todos = self.db.todos
        self.recurring_chores = self.db.recurring_chores
        self.daily_reflections = self.db.daily_reflections
        self.journal_entries = self.db.journal_entries
        self._ensure_indexes()

    def ping(self) -> None:
        self.client.admin.command("ping")

    def _ensure_indexes(self) -> None:
        self.users.create_index([("user_id", ASCENDING)], unique=True)
        self.todos.create_index([("user_id", ASCENDING), ("status", ASCENDING), ("priority", ASCENDING)])
        self.todos.create_index([("user_id", ASCENDING), ("status", ASCENDING), ("project_type", ASCENDING)])
        self.todos.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        self.todos.create_index([("user_id", ASCENDING), ("deadline", ASCENDING)])
        self.recurring_chores.create_index([("user_id", ASCENDING), ("name", ASCENDING)], unique=True)
        self.recurring_chores.create_index([("user_id", ASCENDING), ("next_due_date", ASCENDING)])
        # Migrate from single-question-per-day index to per-question-per-day index.
        for index in self.daily_reflections.list_indexes():
            keys = index.get("key", {})
            if list(keys.items()) == [("user_id", 1), ("asked_for_date", 1)] and index.get("unique"):
                self.daily_reflections.drop_index(index["name"])
                break
        self.daily_reflections.create_index(
            [("user_id", ASCENDING), ("asked_for_date", ASCENDING), ("question_key", ASCENDING)],
            unique=True,
        )
        self.daily_reflections.create_index([("user_id", ASCENDING), ("asked_at", DESCENDING)])
        self.daily_reflections.create_index([("user_id", ASCENDING), ("answered_at", DESCENDING)])
        self.journal_entries.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])

    def upsert_user(self, user_id: int, username: str, first_name: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": username or "",
                    "first_name": first_name or "",
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "main_goal": "make money",
                },
            },
            upsert=True,
        )
        self.ensure_default_chores(user_id)
        return self.get_user_profile(user_id)

    def get_user_profile(self, user_id: int) -> dict[str, Any]:
        profile = self.users.find_one({"user_id": user_id}) or {}
        if "main_goal" not in profile:
            profile["main_goal"] = "make money"
        return profile

    def list_user_ids(self) -> list[int]:
        return [doc["user_id"] for doc in self.users.find({}, {"_id": 0, "user_id": 1})]

    def set_main_goal(self, user_id: int, main_goal: str) -> None:
        self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "main_goal": main_goal.strip(),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    def ensure_default_chores(self, user_id: int) -> None:
        now = datetime.now(timezone.utc)
        today = now.date()
        legacy = self.recurring_chores.find_one({"user_id": user_id, "name": LEGACY_COMBINED_CHORE_NAME})
        legacy_next_due = legacy.get("next_due_date") if legacy else None
        legacy_last_completed = legacy.get("last_completed_at") if legacy else None
        if legacy:
            self.recurring_chores.delete_one({"_id": legacy["_id"], "user_id": user_id})

        for chore in DEFAULT_WEEKEND_CHORES:
            name = chore["name"]
            interval_days = int(chore["interval_days"])
            preferred_weekday = int(chore["preferred_weekday"])
            first_due_date = _next_weekday_on_or_after(today, preferred_weekday)
            default_next_due = _at_start_of_day_utc(first_due_date)
            next_due_seed = legacy_next_due if isinstance(legacy_next_due, datetime) else default_next_due
            self.recurring_chores.update_one(
                {"user_id": user_id, "name": name},
                {
                    "$setOnInsert": {
                        "user_id": user_id,
                        "name": name,
                        "interval_days": interval_days,
                        "preferred_weekday": preferred_weekday,
                        "next_due_date": next_due_seed,
                        "created_at": now,
                        "updated_at": now,
                        "last_completed_at": legacy_last_completed,
                    },
                },
                upsert=True,
            )

    def list_chores(self, user_id: int, limit: int = 25) -> list[dict[str, Any]]:
        return list(
            self.recurring_chores.find({"user_id": user_id}).sort(
                [("next_due_date", ASCENDING), ("name", ASCENDING)]
            ).limit(limit)
        )

    def ensure_daily_reflection_prompt(
        self,
        user_id: int,
        question_key: str,
        question: str,
        asked_at: Optional[datetime] = None,
    ) -> bool:
        now = asked_at or datetime.now(timezone.utc)
        date_key = now.date().isoformat()
        result = self.daily_reflections.update_one(
            {
                "user_id": user_id,
                "asked_for_date": date_key,
                "question_key": question_key,
            },
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "question_key": question_key,
                    "question": question.strip(),
                    "asked_for_date": date_key,
                    "asked_at": now,
                    "answer": None,
                    "answered_at": None,
                    "skipped": False,
                    "skipped_at": None,
                    "skip_note": None,
                }
            },
            upsert=True,
        )
        return result.upserted_id is not None

    def get_pending_reflections(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        return list(
            self.daily_reflections.find(
                {
                    "user_id": user_id,
                    "answer": None,
                    "skipped": {"$ne": True},
                }
            )
            .sort([("asked_at", ASCENDING), ("question_key", ASCENDING)])
            .limit(limit)
        )

    def get_pending_reflection(self, user_id: int) -> Optional[dict[str, Any]]:
        pending = self.get_pending_reflections(user_id=user_id, limit=1)
        return pending[0] if pending else None

    def save_pending_reflection_answer(self, user_id: int, answer: str) -> bool:
        pending = self.get_pending_reflection(user_id)
        if not pending:
            return False

        cleaned = " ".join(answer.split())
        if not cleaned:
            return False

        result = self.daily_reflections.update_one(
            {"_id": pending["_id"], "user_id": user_id, "answer": None},
            {
                "$set": {
                    "answer": cleaned[:4000],
                    "answered_at": datetime.now(timezone.utc),
                    "skipped": False,
                    "skipped_at": None,
                    "skip_note": None,
                }
            },
        )
        return result.modified_count == 1

    def pass_pending_reflection(self, user_id: int, skip_note: str = "pass") -> bool:
        pending = self.get_pending_reflection(user_id)
        if not pending:
            return False

        result = self.daily_reflections.update_one(
            {"_id": pending["_id"], "user_id": user_id, "answer": None},
            {
                "$set": {
                    "answer": "",
                    "answered_at": datetime.now(timezone.utc),
                    "skipped": True,
                    "skipped_at": datetime.now(timezone.utc),
                    "skip_note": skip_note[:120],
                }
            },
        )
        return result.modified_count == 1

    def count_pending_reflections(self, user_id: int) -> int:
        return self.daily_reflections.count_documents(
            {
                "user_id": user_id,
                "answer": None,
                "skipped": {"$ne": True},
            }
        )

    def get_recent_reflection_answers(self, user_id: int, limit: int = 12) -> list[str]:
        return [
            entry["answer"]
            for entry in self.daily_reflections.find(
                {
                    "user_id": user_id,
                    "answer": {"$nin": [None, ""]},
                    "skipped": {"$ne": True},
                }
            )
            .sort("answered_at", DESCENDING)
            .limit(limit)
        ]

    def list_due_chores(self, user_id: int, on_date: Optional[date] = None, limit: int = 25) -> list[dict[str, Any]]:
        day = on_date or datetime.now(timezone.utc).date()
        due_until = _at_end_of_day_utc(day)
        return list(
            self.recurring_chores.find(
                {
                    "user_id": user_id,
                    "next_due_date": {"$lte": due_until},
                }
            ).sort([("next_due_date", ASCENDING), ("interval_days", ASCENDING)]).limit(limit)
        )

    def mark_chore_done(self, user_id: int, chore_id: str, completed_at: Optional[datetime] = None) -> Optional[dict[str, Any]]:
        object_id = _safe_object_id(chore_id)
        if not object_id:
            return None

        chore = self.recurring_chores.find_one({"_id": object_id, "user_id": user_id})
        if not chore:
            return None

        now = completed_at or datetime.now(timezone.utc)
        done_date = now.date()
        interval_days = int(chore.get("interval_days", 7))
        preferred_weekday = int(chore.get("preferred_weekday", 5))
        raw_next_due = done_date + timedelta(days=interval_days)
        next_due_date = _next_weekday_on_or_after(raw_next_due, preferred_weekday)

        self.recurring_chores.update_one(
            {"_id": object_id, "user_id": user_id},
            {
                "$set": {
                    "last_completed_at": now,
                    "next_due_date": _at_start_of_day_utc(next_due_date),
                    "updated_at": now,
                }
            },
        )
        return self.recurring_chores.find_one({"_id": object_id, "user_id": user_id})

    def postpone_chore_to_next_weekend(
        self, user_id: int, chore_id: str, passed_at: Optional[datetime] = None
    ) -> Optional[dict[str, Any]]:
        object_id = _safe_object_id(chore_id)
        if not object_id:
            return None

        chore = self.recurring_chores.find_one({"_id": object_id, "user_id": user_id})
        if not chore:
            return None

        now = passed_at or datetime.now(timezone.utc)
        preferred_weekday = int(chore.get("preferred_weekday", 5))
        next_due_date = _next_weekday_on_or_after(now.date() + timedelta(days=1), preferred_weekday)

        self.recurring_chores.update_one(
            {"_id": object_id, "user_id": user_id},
            {
                "$set": {
                    "next_due_date": _at_start_of_day_utc(next_due_date),
                    "updated_at": now,
                }
            },
        )
        return self.recurring_chores.find_one({"_id": object_id, "user_id": user_id})

    def add_todo(self, user_id: int, title: str, priority: int, deadline: Optional[datetime]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cleaned_title = title.strip()
        resolved_deadline = deadline if deadline is not None else _default_deadline_one_month(now)
        doc = {
            "user_id": user_id,
            "title": cleaned_title,
            "priority": int(priority),
            "project_type": infer_project_type(cleaned_title),
            "deadline": resolved_deadline,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        result = self.todos.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    def _sort_todos(self, todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            todos,
            key=lambda todo: (
                todo.get("priority", 2),
                todo.get("deadline") is None,
                todo.get("deadline") or MAX_AWARE_DT,
                todo.get("created_at") or MAX_AWARE_DT,
            ),
        )

    def list_active_todos(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        todos = list(self.todos.find({"user_id": user_id, "status": "active"}))
        return self._sort_todos(todos)[:limit]

    def get_recent_completed_todos(self, user_id: int, days: int = 120, limit: int = 300) -> list[dict[str, Any]]:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        return list(
            self.todos.find(
                {
                    "user_id": user_id,
                    "status": "done",
                    "completed_at": {"$gte": threshold},
                }
            )
            .sort("completed_at", DESCENDING)
            .limit(limit)
        )

    def get_stale_todos(self, user_id: int, stale_days: int, limit: int = 10) -> list[dict[str, Any]]:
        threshold = datetime.now(timezone.utc) - timedelta(days=stale_days)
        todos = list(
            self.todos.find(
                {
                    "user_id": user_id,
                    "status": "active",
                    "created_at": {"$lte": threshold},
                }
            )
        )
        return self._sort_todos(todos)[:limit]

    def get_overdue_todos(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        todos = list(
            self.todos.find(
                {
                    "user_id": user_id,
                    "status": "active",
                    "deadline": {"$ne": None, "$lt": now},
                }
            )
        )
        return self._sort_todos(todos)[:limit]

    def mark_todo_done(self, user_id: int, todo_id: str) -> bool:
        object_id = _safe_object_id(todo_id)
        if not object_id:
            return False
        result = self.todos.update_one(
            {"_id": object_id, "user_id": user_id, "status": "active"},
            {
                "$set": {
                    "status": "done",
                    "completed_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return result.modified_count == 1

    def delete_todo(self, user_id: int, todo_id: str) -> bool:
        object_id = _safe_object_id(todo_id)
        if not object_id:
            return False
        result = self.todos.delete_one({"_id": object_id, "user_id": user_id})
        return result.deleted_count == 1

    def add_journal_entry(self, user_id: int, text: str, source: str = "chat") -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        self.journal_entries.insert_one(
            {
                "user_id": user_id,
                "text": cleaned[:1200],
                "source": source,
                "created_at": datetime.now(timezone.utc),
            }
        )

    def get_recent_journal_entries(self, user_id: int, limit: int = 12) -> list[str]:
        return [
            entry["text"]
            for entry in self.journal_entries.find({"user_id": user_id}).sort("created_at", DESCENDING).limit(limit)
        ]

    def get_stats(self, user_id: int) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        last_7 = now - timedelta(days=7)
        last_30 = now - timedelta(days=30)
        return {
            "active": self.todos.count_documents({"user_id": user_id, "status": "active"}),
            "done_7d": self.todos.count_documents(
                {"user_id": user_id, "status": "done", "completed_at": {"$gte": last_7}}
            ),
            "done_30d": self.todos.count_documents(
                {"user_id": user_id, "status": "done", "completed_at": {"$gte": last_30}}
            ),
            "created_7d": self.todos.count_documents({"user_id": user_id, "created_at": {"$gte": last_7}}),
            "created_30d": self.todos.count_documents({"user_id": user_id, "created_at": {"$gte": last_30}}),
        }


def _safe_object_id(raw: str) -> Optional[ObjectId]:
    try:
        return ObjectId(raw)
    except (InvalidId, TypeError):
        return None


def _at_start_of_day_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _at_end_of_day_utc(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=timezone.utc)


def _next_weekday_on_or_after(day: date, weekday: int) -> date:
    delta = (weekday - day.weekday()) % 7
    return day + timedelta(days=delta)


def _default_deadline_one_month(reference: datetime) -> datetime:
    year = reference.year
    month = reference.month
    day = reference.day

    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year
    max_next_month_day = calendar.monthrange(next_year, next_month)[1]
    due_day = min(day, max_next_month_day)
    due_date = date(next_year, next_month, due_day)
    return datetime.combine(due_date, time(23, 59, 59, tzinfo=timezone.utc))

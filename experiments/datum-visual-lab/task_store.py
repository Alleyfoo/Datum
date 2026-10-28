"""Local task history for the read-only Datum task experiment.

Each mutation uses one SQLite transaction. Source systems are never written.
Initiator values are unverified labels, not authentication or authorization.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

TASK_TYPES = {"repair_investigation", "supplier_conflict_review"}
INITIATORS = {"agent", "human", "system"}
REVIEW_DECISIONS = {"reviewed", "needs_more_information", "disagree"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _initiator(value: str) -> str:
    if value not in INITIATORS:
        raise ValueError("Initiator must be agent, human, or system")
    return value


def _task_id(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("task-") or len(value) != 37:
        raise ValueError("Invalid task identifier")
    try:
        uuid.UUID(hex=value[5:])
    except ValueError as exc:
        raise ValueError("Invalid task identifier") from exc
    return value


class TaskStore:
    """Small durable task store; every method opens its own bounded connection."""

    def __init__(self, path: str | Path | None = None):
        selected = path if path is not None else os.environ.get("DATUM_TASK_DB")
        self.path = Path(selected) if selected else Path(__file__).with_name("task_experiment.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL,
                    parameters TEXT NOT NULL, recommendation TEXT,
                    next_steps TEXT NOT NULL, outstanding_questions TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    parameters TEXT NOT NULL, result TEXT NOT NULL,
                    created_at TEXT NOT NULL, initiator TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    evaluation_id TEXT NOT NULL REFERENCES evaluations(evaluation_id),
                    decision TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
                    initiator TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id), event_type TEXT NOT NULL,
                    details TEXT NOT NULL, created_at TEXT NOT NULL, initiator TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS evaluations_task ON evaluations(task_id, created_at);
                CREATE INDEX IF NOT EXISTS reviews_task ON reviews(task_id, created_at);
                CREATE INDEX IF NOT EXISTS events_task ON events(task_id, event_id);
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _require_task(db: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (_task_id(task_id),)).fetchone()
        if row is None:
            raise ValueError("Task not found")
        return row

    @staticmethod
    def _event(db: sqlite3.Connection, task_id: str, kind: str, details: dict[str, Any], actor: str, now: str) -> None:
        db.execute("INSERT INTO events(task_id,event_type,details,created_at,initiator) VALUES(?,?,?,?,?)",
                   (task_id, kind, _json(details), now, actor))

    def create(self, task_type: str, parameters: dict[str, Any], initiator: str,
               recommendation: str | None = None, next_steps: list[str] | None = None) -> dict[str, Any]:
        if task_type not in TASK_TYPES:
            raise ValueError("Unknown task type")
        if not isinstance(parameters, dict):
            raise ValueError("Parameters must be an object")
        if recommendation is not None and not isinstance(recommendation, str):
            raise ValueError("Recommendation must be text or null")
        if next_steps is not None and (not isinstance(next_steps, list) or not all(isinstance(x, str) for x in next_steps)):
            raise ValueError("Next steps must be a list of text")
        actor = _initiator(initiator)
        tid, now = "task-" + uuid.uuid4().hex, _timestamp()
        with self._connection() as db:
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)",
                       (tid, task_type, _json(parameters), recommendation, _json(next_steps or []), _json([]), now, now, actor))
            self._event(db, tid, "task_created", {"task_type": task_type, "parameters": parameters}, actor, now)
        return self.get(tid)

    def get(self, task_id: str, *, reopen: bool = False, initiator: str = "system") -> dict[str, Any]:
        actor = _initiator(initiator)
        with self._connection() as db:
            # A consistent snapshot prevents mixing a task's old parameters with new history.
            db.execute("BEGIN IMMEDIATE" if reopen else "BEGIN")
            row = self._require_task(db, task_id)
            if reopen:
                self._event(db, task_id, "task_reopened", {}, actor, _timestamp())
            evaluations = [dict(r) for r in db.execute("SELECT * FROM evaluations WHERE task_id=? ORDER BY rowid", (task_id,))]
            reviews = [dict(r) for r in db.execute("SELECT * FROM reviews WHERE task_id=? ORDER BY rowid", (task_id,))]
            events = [dict(r) for r in db.execute("SELECT * FROM events WHERE task_id=? ORDER BY event_id", (task_id,))]
            for item in evaluations:
                item["parameters"] = json.loads(item["parameters"])
                item["result"] = json.loads(item["result"])
            for item in events:
                item["details"] = json.loads(item["details"])
            return {
                "task_id": row["task_id"], "task_type": row["task_type"], "parameters": json.loads(row["parameters"]),
                "recommendation": row["recommendation"], "next_steps": json.loads(row["next_steps"]),
                "outstanding_questions": json.loads(row["outstanding_questions"]),
                "created_at": row["created_at"], "updated_at": row["updated_at"], "created_by": row["created_by"],
                "current_result": evaluations[-1]["result"] if evaluations else None,
                "evaluations": evaluations, "reviews": reviews, "events": events,
                "identity_note": "Initiators are unverified labels; no business authorization is recorded.",
            }

    def record_tool_invocation(self, task_id: str, tool_name: str, initiator: str) -> None:
        actor = _initiator(initiator)
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("Tool name required")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_task(db, task_id)
            self._event(db, task_id, "tool_invoked", {"tool": tool_name}, actor, _timestamp())

    def evaluate(self, task_id: str, parameters: dict[str, Any], result: dict[str, Any], initiator: str) -> dict[str, Any]:
        """Append the already validated domain result and its receipt atomically."""
        actor = _initiator(initiator)
        if not isinstance(parameters, dict) or not isinstance(result, dict) or result.get("parameters") != parameters:
            raise ValueError("Result must contain the evaluated parameters")
        receipt = result.get("receipt")
        if not isinstance(receipt, dict) or not all(k in receipt for k in ("run_id", "input_sha256", "source_hashes", "ruleset")):
            raise ValueError("Evaluation receipt is incomplete")
        unresolved = result.get("unresolved")
        if not isinstance(unresolved, list) or not all(isinstance(x, str) for x in unresolved):
            raise ValueError("Unresolved questions must be a list of text")
        # Serialize before opening the transaction; unsupported or nonfinite values cannot partly persist.
        params_json, result_json, unresolved_json = _json(parameters), _json(result), _json(unresolved)
        eid, now = "eval-" + uuid.uuid4().hex, _timestamp()
        with self._connection() as db:
            # Serialize read/modify/write: previous parameters and their audit event
            # must describe the immediately preceding committed task state.
            db.execute("BEGIN IMMEDIATE")
            task = self._require_task(db, task_id)
            if result.get("task_type") != task["task_type"]:
                raise ValueError("Evaluation task type does not match task")
            previous = json.loads(task["parameters"])
            self._event(db, task_id, "parameters_validated", {"parameters": parameters}, actor, now)
            if previous != parameters:
                self._event(db, task_id, "parameter_changed", {"before": previous, "after": parameters}, actor, now)
            self._event(db, task_id, "data_sources_accessed", {"source_hashes": receipt["source_hashes"], "input_sha256": receipt["input_sha256"]}, actor, now)
            self._event(db, task_id, "rule_applied", {"ruleset": receipt["ruleset"]}, actor, now)
            db.execute("INSERT INTO evaluations VALUES(?,?,?,?,?,?)", (eid, task_id, params_json, result_json, now, actor))
            db.execute("UPDATE tasks SET parameters=?, outstanding_questions=?, updated_at=? WHERE task_id=?", (params_json, unresolved_json, now, task_id))
            self._event(db, task_id, "evaluation_completed", {"evaluation_id": eid, "run_id": receipt["run_id"]}, actor, now)
        return self.get(task_id)

    def review(self, task_id: str, decision: str, note: str, initiator: str = "human",
               evaluation_id: str | None = None) -> dict[str, Any]:
        """Record a claimed human review, not an authorization.

        Supplying the displayed evaluation ID rejects a stale submission if another
        evaluation was saved meanwhile. Callers with an interactive UI should send it.
        """
        actor = _initiator(initiator)
        if actor != "human":
            raise ValueError("Review requires a human-labelled initiator")
        if decision not in REVIEW_DECISIONS or not isinstance(note, str) or len(note) > 4000:
            raise ValueError("Invalid review decision or note")
        rid, now = "review-" + uuid.uuid4().hex, _timestamp()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_task(db, task_id)
            evaluation = db.execute("SELECT evaluation_id FROM evaluations WHERE task_id=? ORDER BY rowid DESC LIMIT 1", (task_id,)).fetchone()
            if evaluation is None:
                raise ValueError("A human review requires an evaluation")
            eid = evaluation["evaluation_id"]
            if evaluation_id is not None and evaluation_id != eid:
                raise ValueError("Evaluation changed; reopen the task before recording review")
            db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)", (rid, task_id, eid, decision, note, now, actor))
            db.execute("UPDATE tasks SET updated_at=? WHERE task_id=?", (now, task_id))
            self._event(db, task_id, "human_review_recorded", {"review_id": rid, "evaluation_id": eid, "decision": decision, "note": note, "authorization": False}, actor, now)
        return self.get(task_id)

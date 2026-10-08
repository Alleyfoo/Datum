"""Ticket spine: tasks and documents in one number space, leases, links and an attributed journal.

Modelled on Subroutine (github.com/simonholliday/subroutine), as the owner decided:

- one numbering scheme: a task and a document never share a number, and no number is reused;
- a decision or a finding is a document, which records what was concluded;
- a comment records what happened; comments and every state change are journal entries, and
  the journal is append-only (enforced by the database, not only by this code);
- a `blocks` link keeps a task out of the ready list until its blocker is done;
- a claim is a lease: it runs out by itself, every write by its holder renews it, finishing
  releases it, and a holder whose lease ran out must claim again.

From the lab's case store (desk/cases.py) come the mechanics: SQLite with short connections,
`BEGIN IMMEDIATE` for writes, the claim checked in the same transaction as the write it guards,
and every event attributed to an actor. Origin in docs/provenance.md.

Roles live on the user record (`approver`, `worker`; one person may hold both) and on every
action, which records the role it was taken in. A service account, such as the intake hook,
holds no role and acts as `system`. There is no authentication: names are coordination labels.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

ROLES = ("approver", "worker")
USER_KINDS = ("person", "agent", "service")
TASK_STATUSES = ("open", "in_progress", "needs_input", "done")
DOCUMENT_TYPES = ("decision", "finding")
LINK_TYPES = ("blocks", "about")
LEASE = timedelta(minutes=30)  # placeholder, not tuned
SYSTEM = "system"
#: words that make a name agent-like; such a name is never accepted as an approver
AGENT_WORDS = {"agent", "assistant", "llm", "system", "mcp", "claude", "bot", "gpt", "chatgpt",
               "copilot", "gemini", "codex", "ollama", "hook"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('person', 'agent', 'service')),
    roles TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
    number INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('task', 'document')),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL,
    origin TEXT UNIQUE,
    assignee TEXT REFERENCES users(name),
    claimed_by TEXT REFERENCES users(name),
    lease_until TEXT,
    created_by TEXT NOT NULL REFERENCES users(name),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS links (
    source INTEGER NOT NULL REFERENCES items(number),
    type TEXT NOT NULL CHECK (type IN ('blocks', 'about')),
    target INTEGER NOT NULL REFERENCES items(number),
    created_by TEXT NOT NULL REFERENCES users(name),
    created_at TEXT NOT NULL,
    PRIMARY KEY (source, type, target));
CREATE TABLE IF NOT EXISTS journal (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    item INTEGER REFERENCES items(number),
    actor TEXT NOT NULL REFERENCES users(name),
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT NOT NULL,
    at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS items_no_delete BEFORE DELETE ON items
BEGIN SELECT RAISE(ABORT, 'items are never deleted, so a number is never reused'); END;
"""


class RecordError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def require(condition, code: str, message: str) -> None:
    if not condition:
        raise RecordError(code, message)


def text(value, field: str, maximum: int = 4000) -> str:
    require(isinstance(value, str) and value.strip() != "" and len(value) <= maximum,
            "invalid_argument", f"{field} needs non-empty text of at most {maximum} characters")
    return value


def agent_like(name: str) -> bool:
    """True when any word of the name, split at punctuation and camel case, is an agent word."""
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name or "")
    return any(word.lower() in AGENT_WORDS for word in words)


def _encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Store:
    def __init__(self, path, *, clock: Optional[Callable[[], datetime]] = None, lease: timedelta = LEASE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lease = lease
        db = self._connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")  # kept by the file: readers never block the writer
            db.executescript(SCHEMA)
            if db.execute("SELECT 1 FROM users WHERE name=?", (SYSTEM,)).fetchone() is None:
                db.execute("INSERT INTO users VALUES (?,?,?,?)", (SYSTEM, "service", "", self.now()))
        finally:
            db.close()

    def ensure(self, script: str) -> None:
        """Create a module's own tables (CREATE ... IF NOT EXISTS statements) once per store."""
        done = self.__dict__.setdefault("_ensured", set())
        if script in done:
            return
        db = self._connect()
        try:
            db.executescript(script)
        finally:
            db.close()
        done.add(script)

    # -- connections and the journal -------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=NORMAL")  # with WAL: commits stay atomic, fewer disk syncs
        return db

    def now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat(timespec="seconds")

    @contextmanager
    def transaction(self):
        """One short write transaction; everything inside commits or nothing does."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @contextmanager
    def reading(self):
        db = self._connect()
        try:
            db.execute("BEGIN")
            yield db
            db.execute("COMMIT")
        finally:
            db.close()

    def write_journal(self, db, item: Optional[int], actor: str, role: str, action: str,
                      details: Optional[dict] = None) -> int:
        cursor = db.execute("INSERT INTO journal (item, actor, role, action, details, at) VALUES (?,?,?,?,?,?)",
                            (item, actor, role, action, _encode(details or {}), self.now()))
        return cursor.lastrowid

    # -- users and roles ------------------------------------------------------------------

    def add_user(self, name: str, roles: Iterable[str] = (), *, kind: str = "person", by: str = SYSTEM) -> dict:
        name = text(name, "name", 100)
        roles = tuple(sorted(set(roles)))
        require(kind in USER_KINDS, "invalid_argument", f"user kind must be one of {USER_KINDS}")
        require(set(roles) <= set(ROLES), "invalid_role", f"roles must be among {ROLES}")
        require(kind != "service" or not roles, "invalid_role", "a service account holds no role")
        if "approver" in roles:
            require(kind == "person", "agent_approver", "only a person can hold the approver role")
            require(not agent_like(name), "agent_approver", f"{name!r} looks like an agent's name")
        with self.transaction() as db:
            require(db.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone() is None,
                    "user_exists", f"user {name} already exists")
            self._user(db, by)
            db.execute("INSERT INTO users VALUES (?,?,?,?)", (name, kind, ",".join(roles), self.now()))
            self.write_journal(db, None, by, self.acting_role(db, by), "user_added",
                               {"name": name, "kind": kind, "roles": list(roles)})
        return self.user(name)

    def _user(self, db, name: str) -> dict:
        row = db.execute("SELECT * FROM users WHERE name=?", (name,)).fetchone()
        require(row is not None, "unknown_user", f"unknown user {name!r}")
        user = dict(row)
        user["roles"] = tuple(r for r in user["roles"].split(",") if r)
        return user

    def user(self, name: str) -> dict:
        with self.reading() as db:
            return self._user(db, name)

    def acting_role(self, db, name: str, wanted: Optional[str] = None) -> str:
        """The role an action is taken in: the one asked for, which the user must hold."""
        user = self._user(db, name)
        if user["kind"] == "service":
            require(wanted in (None, SYSTEM), "role_missing", f"{name} is a service account and holds no role")
            return SYSTEM
        if wanted is not None:
            require(wanted in user["roles"], "role_missing", f"{name} does not hold the {wanted} role")
            return wanted
        require(bool(user["roles"]), "role_missing", f"{name} holds no role")
        return "worker" if "worker" in user["roles"] else user["roles"][0]

    def approver(self, db, name: str) -> str:
        """Check that a name may approve: a person, holding the role, not agent-like."""
        user = self._user(db, name)
        require(user["kind"] == "person" and not agent_like(name), "agent_approver",
                f"{name!r} is not accepted as an approver: approvals need a named person")
        return self.acting_role(db, name, "approver")

    # -- items ------------------------------------------------------------------------------

    def _item(self, db, number: int) -> dict:
        row = db.execute("SELECT * FROM items WHERE number=?", (number,)).fetchone()
        require(row is not None, "unknown_item", f"no item #{number}")
        item = dict(row)
        item["data"] = json.loads(item["data"])
        item["lease_active"] = self._lease_active(item)
        return item

    def _lease_active(self, item: dict) -> bool:
        return (item["claimed_by"] is not None and item["lease_until"] is not None
                and datetime.fromisoformat(item["lease_until"]) > self.clock())

    def get(self, number: int) -> dict:
        with self.reading() as db:
            return self._item(db, number)

    def find(self, origin: str) -> Optional[int]:
        with self.reading() as db:
            row = db.execute("SELECT number FROM items WHERE origin=?", (origin,)).fetchone()
        return row[0] if row else None

    def create_item(self, db, actor: str, kind: str, type_: str, title: str, *, body: str = "",
                    data: Optional[dict] = None, status: str, origin: Optional[str] = None,
                    role: Optional[str] = None) -> int:
        title = text(title, "title", 200)
        stamp = self.now()
        cursor = db.execute(
            "INSERT INTO items (kind, type, title, body, data, status, origin, created_by, created_at,"
            " updated_at, version) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
            (kind, type_, title, body, _encode(data or {}), status, origin, actor, stamp, stamp))
        number = cursor.lastrowid
        self.write_journal(db, number, actor, self.acting_role(db, actor, role), "created",
                           {"kind": kind, "type": type_, "title": title, "origin": origin})
        return number

    def add_task(self, actor: str, title: str, *, body: str = "", data: Optional[dict] = None,
                 origin: Optional[str] = None, role: Optional[str] = None) -> int:
        """Open a task. A task with the same origin is returned instead of a second one."""
        with self.transaction() as db:
            if origin is not None:
                row = db.execute("SELECT number FROM items WHERE origin=?", (origin,)).fetchone()
                if row:
                    return row[0]
            return self.create_item(db, actor, "task", "task", title, body=body, data=data,
                                    status="open", origin=origin, role=role)

    def add_document(self, actor: str, type_: str, title: str, body: str, *, data: Optional[dict] = None,
                     about: Optional[int] = None, role: Optional[str] = None) -> int:
        with self.transaction() as db:
            return self.document(db, actor, type_, title, body, data=data, about=about, role=role)

    def document(self, db, actor: str, type_: str, title: str, body: str, *, data: Optional[dict] = None,
                 about: Optional[int] = None, role: Optional[str] = None) -> int:
        """Write a decision or a finding inside an open transaction, optionally about another item."""
        require(type_ in DOCUMENT_TYPES, "invalid_argument", f"a document is one of {DOCUMENT_TYPES}")
        number = self.create_item(db, actor, "document", type_, title, body=text(body, "body", 200_000),
                                  data=data, status="current", role=role)
        if about is not None:
            self._item(db, about)
            self._link(db, actor, number, "about", about, role)
            if self._holds(db, about, actor):
                self._renew(db, about)
        return number

    def update(self, db, number: int, actor: str, *, role: Optional[str] = None,
               expected_version: Optional[int] = None, action: str = "updated",
               note: Optional[dict] = None, **fields) -> dict:
        """Change fields of an item inside an open transaction; one journal entry per call.

        `note` adds details to that entry, such as the reason a person gave.
        """
        item = self._item(db, number)
        require(expected_version is None or expected_version == item["version"], "version_conflict",
                f"#{number} is at version {item['version']}, not {expected_version}")
        allowed = {"title", "body", "data", "status", "assignee"}
        require(set(fields) <= allowed, "invalid_argument", f"only {sorted(allowed)} can be updated")
        if "status" in fields:
            statuses = TASK_STATUSES if item["kind"] == "task" else ("current",)
            require(fields["status"] in statuses, "invalid_status", f"status must be one of {statuses}")
        changes = {k: v for k, v in fields.items() if v != item[k]}
        if not changes and not note:
            return item
        if changes:
            columns = {k: (_encode(v) if k == "data" else v) for k, v in changes.items()}
            assignments = ", ".join(f"{k}=?" for k in columns)
            db.execute(f"UPDATE items SET {assignments}, updated_at=?, version=version+1 WHERE number=?",
                       (*columns.values(), self.now(), number))
        details = dict(note or {})
        details.update({k: {"before": item[k], "after": v} for k, v in changes.items() if k != "data"})
        if "data" in changes:
            details["data"] = sorted(k for k in set(item["data"]) | set(changes["data"])
                                     if item["data"].get(k) != changes["data"].get(k))
        finished = changes.get("status") == "done"
        if finished and item["claimed_by"]:
            details["released"] = item["claimed_by"]  # finishing hands the claim back
        self.write_journal(db, number, actor, self.acting_role(db, actor, role), action, details)
        if finished:
            db.execute("UPDATE items SET claimed_by=NULL, lease_until=NULL WHERE number=?", (number,))
        elif self._holds(db, number, actor):
            self._renew(db, number)
        return self._item(db, number)

    # -- claims as leases ---------------------------------------------------------------------

    def _holds(self, db, number: int, actor: str) -> bool:
        item = self._item(db, number)
        return item["claimed_by"] == actor and item["lease_active"]

    def _renew(self, db, number: int) -> None:
        until = (self.clock() + self.lease).astimezone(timezone.utc).isoformat(timespec="seconds")
        db.execute("UPDATE items SET lease_until=? WHERE number=?", (until, number))

    def hold(self, db, number: int, actor: str) -> dict:
        """Require the actor's live claim on a task before a state change, and renew it."""
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        require(item["status"] != "done", "item_done", f"#{number} is done")
        if item["claimed_by"] == actor and not item["lease_active"]:
            raise RecordError("claim_expired", f"your lease on #{number} ran out at {item['lease_until']}; claim it again")
        require(item["claimed_by"] == actor, "claim_required", f"claim #{number} before changing it")
        self._renew(db, number)
        return self._item(db, number)

    def take(self, db, number: int, actor: str, role: Optional[str] = None) -> dict:
        """Claim inside an open transaction: free, expired, or already the actor's."""
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        require(item["status"] != "done", "item_done", f"#{number} is done")
        if item["lease_active"] and item["claimed_by"] != actor:
            raise RecordError("claim_conflict",
                              f"#{number} is held by {item['claimed_by']} until {item['lease_until']}")
        details = {}
        if item["claimed_by"] not in (None, actor):
            details = {"previous": item["claimed_by"], "expired_at": item["lease_until"]}
        elif item["claimed_by"] == actor and item["lease_active"]:
            details = {"renewed": True}
        db.execute("UPDATE items SET claimed_by=? WHERE number=?", (actor, number))
        self._renew(db, number)
        self.write_journal(db, number, actor, self.acting_role(db, actor, role), "claimed", details)
        return self._item(db, number)

    def claim(self, number: int, actor: str, role: Optional[str] = None) -> dict:
        with self.transaction() as db:
            return self.take(db, number, actor, role)

    def release(self, number: int, actor: str) -> dict:
        with self.transaction() as db:
            return self.let_go(db, number, actor)

    def let_go(self, db, number: int, actor: str) -> dict:
        item = self._item(db, number)
        require(item["claimed_by"] == actor, "release_forbidden", f"only the holder can release #{number}")
        db.execute("UPDATE items SET claimed_by=NULL, lease_until=NULL WHERE number=?", (number,))
        self.write_journal(db, number, actor, self.acting_role(db, actor), "released", {})
        return self._item(db, number)

    # -- what people do on a ticket -----------------------------------------------------------

    def set_status(self, number: int, actor: str, status: str, *, role: Optional[str] = None,
                   expected_version: Optional[int] = None) -> dict:
        with self.transaction() as db:
            self.hold(db, number, actor)
            return self.update(db, number, actor, role=role, expected_version=expected_version,
                               action="status_changed", status=status)

    def comment(self, number: int, actor: str, body: str, *, role: Optional[str] = None) -> int:
        """A comment records what happened. Anyone may comment, also on a finished item."""
        body = text(body, "body", 20_000)
        with self.transaction() as db:
            self._item(db, number)
            seq = self.write_journal(db, number, actor, self.acting_role(db, actor, role), "comment", {"body": body})
            if self._holds(db, number, actor):
                self._renew(db, number)
            return seq

    def _link(self, db, actor: str, source: int, type_: str, target: int, role: Optional[str] = None) -> None:
        require(type_ in LINK_TYPES, "invalid_argument", f"a link is one of {LINK_TYPES}")
        require(source != target, "invalid_argument", "an item cannot link to itself")
        left, right = self._item(db, source), self._item(db, target)
        if type_ == "blocks":
            require(left["kind"] == right["kind"] == "task", "invalid_argument", "only tasks block tasks")
        db.execute("INSERT OR IGNORE INTO links VALUES (?,?,?,?,?)", (source, type_, target, actor, self.now()))
        self.write_journal(db, source, actor, self.acting_role(db, actor, role), "linked",
                           {"type": type_, "target": target})

    def link(self, actor: str, source: int, type_: str, target: int, *, role: Optional[str] = None) -> None:
        """`link(actor, 42, "blocks", 43)` reads as "42 blocks 43"."""
        with self.transaction() as db:
            self._link(db, actor, source, type_, target, role)

    def linked(self, number: int, type_: str, *, incoming: bool = False) -> List[int]:
        column, other = ("target", "source") if incoming else ("source", "target")
        with self.reading() as db:
            return [r[0] for r in db.execute(
                f"SELECT {other} FROM links WHERE {column}=? AND type=? ORDER BY {other}", (number, type_))]

    def ready(self, actor: Optional[str] = None) -> List[dict]:
        """Tasks someone can start: open or in progress, no unfinished blocker, not held by another."""
        with self.reading() as db:
            rows = db.execute(
                "SELECT number FROM items i WHERE kind='task' AND status IN ('open','in_progress')"
                " AND NOT EXISTS (SELECT 1 FROM links l JOIN items b ON b.number=l.source"
                "                 WHERE l.target=i.number AND l.type='blocks' AND b.status!='done')"
                " ORDER BY number").fetchall()
            items = [self._item(db, r[0]) for r in rows]
        return [i for i in items if not i["lease_active"] or i["claimed_by"] == actor]

    def journal(self, number: Optional[int] = None) -> List[dict]:
        query = "SELECT * FROM journal" + (" WHERE item=?" if number is not None else "") + " ORDER BY seq"
        with self.reading() as db:
            rows = db.execute(query, (number,) if number is not None else ()).fetchall()
        return [{**dict(r), "details": json.loads(r["details"])} for r in rows]

    def items(self, kind: Optional[str] = None) -> List[dict]:
        with self.reading() as db:
            query = "SELECT number FROM items" + (" WHERE kind=?" if kind else "") + " ORDER BY number"
            return [self._item(db, r[0]) for r in db.execute(query, (kind,) if kind else ())]

    def documents_about(self, number: int, type_: Optional[str] = None) -> List[dict]:
        found = [self.get(n) for n in self.linked(number, "about", incoming=True)]
        return [d for d in found if type_ is None or d["type"] == type_]

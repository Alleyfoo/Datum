"""Ticket spine: tasks and documents in one number space, leases, links and an attributed journal.

Modelled on Subroutine (github.com/simonholliday/subroutine), as the owner decided:

- one numbering scheme: a task and a document never share a number, and no number is reused;
- a decision or a finding is a document, which records what was concluded;
- a comment records what happened; comments and every state change are journal entries, and
  the journal is append-only (enforced by the database, not only by this code). The one exception
  is the owner's (S-del and S-keep, build-plan section 28): a closed ticket is deleted in time, its
  journal and the documents only about it with it, leaving one audit line without content;
- a `blocks` link keeps a task out of the ready list until its blocker's work ends;
- a claim is a lease: it runs out by itself, one day after its holder's last write (owner answer
  P22, build-plan section 20), every write by its holder renews it, the end of the task's work
  releases it, and a holder whose lease ran out must claim again;
- opening an open ticket hands it to an agent: claimed, and `in_progress`; released without a
  decision, it goes back to `open` (owner answers T-open and T-release, build-plan section 10),
  and the release may say why. A lease that runs out leaves the status as it is (owner answer
  Q-stale, section 20). Resuming takes up an open ticket, or one whose holder's lease ran out,
  and the journal records who resumed it (owner answer P26, section 25);
- a task's statuses are `open`, `in_progress`, `needs_input` (it waits on an approver's decision),
  `closed` and `finished` (owner answers S-two and S-states, build-plan sections 27 and 29). Its
  work ends in one of the last two. `closed`: it could not be finished (S-closed). `finished`: it
  is done and correct; only an approver finishes it, with a decision recorded about it, with a
  reason (S-finish), and it stays finished, with its whole history (S-finished). The store kept
  `done` for `closed` before (P25, section 25), and closed a ticket for every end, an approval's
  too; migration steps, run once when an older store opens, rename it, and finish the closed
  tickets an approval ended;
- a worker closes a task that cannot be finished, with the reason (S-close, section 29), and
  whatever path closes a task, a notice on it tells its creator (the item's `created_by`). The
  creator may amend its title or body, each amendment a journal entry with the text before and
  after, and repost it: open again, with its history; or delete it (S-closed, section 27). A
  closed ticket nobody reacts to for CLOSED_RETENTION_DAYS is deleted by the sweep, which runs
  only when called, on the date it is given (S-period, section 29).

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

ROLES = ("approver", "worker")
USER_KINDS = ("person", "agent", "service")
#: a task that could not be finished (owner answer S-closed, build-plan section 27). Named once, here
CLOSED = "closed"  # the owner's name for it (P25, build-plan section 25); the store said "done" before
#: a task that is done and correct, with an approver's decision (owner answers S-finished and S-finish,
#: build-plan sections 27 and 29). It stays finished, and its history is never deleted
FINISHED = "finished"
TASK_STATUSES = ("open", "in_progress", "needs_input", CLOSED, FINISHED)
#: the statuses a task's work ends in: its claim is handed back, and it is not claimed, opened or resumed again
ENDS = (CLOSED, FINISHED)
#: what a decision document says when a task may be finished on it: an approval, or a finish itself
FINISHING_DECISIONS = ("approved", "finished")
#: the store's version, kept in SQLite's user_version; an older store is brought up to it once, when opened
VERSION = 3
DOCUMENT_TYPES = ("decision", "finding")
LINK_TYPES = ("blocks", "about")
LEASE = timedelta(days=1)  # from the holder's last write: the owner's answer to P22 (build-plan section 20)
#: how many days a closed ticket is kept after its last reaction; then the sweep deletes it, with its history
#: (owner answers S-del, S-keep and S-period, build-plan sections 28 and 29). A named setting
CLOSED_RETENTION_DAYS = 30
SYSTEM = "system"
#: words that make a name agent-like; such a name is never accepted as an approver
AGENT_WORDS = {"agent", "assistant", "llm", "system", "mcp", "claude", "bot", "gpt", "chatgpt",
               "copilot", "gemini", "codex", "ollama", "hook"}

SCHEMA = f"""
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
CREATE TABLE IF NOT EXISTS deleting (
    number INTEGER PRIMARY KEY);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete_but_closed BEFORE DELETE ON journal
WHEN NOT EXISTS (SELECT 1 FROM deleting WHERE number = OLD.item)
BEGIN SELECT RAISE(ABORT, 'the journal is append-only: only a deleted closed ticket takes its entries'); END;
CREATE TRIGGER IF NOT EXISTS items_no_delete_but_closed BEFORE DELETE ON items
WHEN NOT EXISTS (SELECT 1 FROM deleting WHERE number = OLD.number)
     OR (OLD.kind = 'task' AND OLD.status != '{CLOSED}')
BEGIN SELECT RAISE(ABORT, 'items are never deleted, but a closed ticket and its documents; no number is reused'); END;
"""
# `deleting` holds the numbers the store deletes, inside the one transaction that deletes them, and is
# empty at every other time: the two delete guards refuse every row it does not name, and any task that
# is not closed. Only _delete fills it. AUTOINCREMENT keeps a deleted number from being used again.


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


def _marks(values) -> str:
    """``?,?,?``: one SQL parameter per value, for ``IN (...)``."""
    return ",".join("?" * len(values))


def notice(number: int, creator: str) -> str:
    """What a closed ticket's creator is told (owner answer S-closed, build-plan section 27)."""
    return (f"#{number} is closed: it could not be finished. {creator}, as its creator you may amend it and "
            f"repost it, which opens it again with its history, or delete it. If nobody reacts to it for "
            f"{CLOSED_RETENTION_DAYS} days, it is deleted, with its history.")


def _moment(when) -> datetime:
    """The date a sweep runs on, in UTC: a datetime with its time zone, or a date, taken at midnight UTC."""
    if isinstance(when, datetime):
        require(when.tzinfo is not None, "invalid_argument", "the sweep's date needs its time zone")
        return when.astimezone(timezone.utc)
    require(isinstance(when, date), "invalid_argument", "the sweep needs the date it runs on")
    return datetime(when.year, when.month, when.day, tzinfo=timezone.utc)


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
            behind = db.execute("PRAGMA user_version").fetchone()[0] < VERSION
        finally:
            db.close()
        if behind:
            self._migrate()

    def _migrate(self) -> None:
        """Bring a store written by older code up to VERSION, in one transaction. Each item a step
        changes gets a journal entry by `system`, with the value before and after. The journal
        itself is never rewritten: it keeps what was written at the time.

        1. The status `done` is called `closed` (owner answer P25, build-plan section 25).
        2. A closed ticket is deleted in time (owner answers S-del and S-period, build-plan sections 28
           and 29): the older delete guards, which refused every delete, give way to the ones in SCHEMA,
           which let the store delete a closed ticket and nothing else. No item changes.
        3. The two end states (owner answers S-two, S-finish and S-closed, build-plan sections 27 and
           29). Older code closed a ticket for every end, an approval's too. A closed ticket whose last
           decision is an approver's approval, with a reason, is finished: it keeps its whole history
           and is never deleted. Each other closed ticket stays closed and gets the notice to its
           creator now, so its CLOSED_RETENTION_DAYS start when its creator is told. No ticket is lost.
        """
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version >= VERSION:
                return  # another connection brought it up while this one waited for the lock
            if version < 1:
                for (number,) in db.execute("SELECT number FROM items WHERE kind='task' AND status='done'"
                                            " ORDER BY number").fetchall():
                    db.execute("UPDATE items SET status=?, updated_at=?, version=version+1 WHERE number=?",
                               (CLOSED, self.now(), number))
                    self.write_journal(db, number, SYSTEM, SYSTEM, "migrated", {
                        "status": {"before": "done", "after": CLOSED},
                        "reason": "the status done is called closed (owner answer P25, build-plan section 25)"})
            if version < 2:
                db.execute("DROP TRIGGER IF EXISTS items_no_delete")
                db.execute("DROP TRIGGER IF EXISTS journal_no_delete")
            if version < 3:
                for row in db.execute("SELECT number, data, created_by FROM items WHERE kind='task' AND status=?"
                                      " ORDER BY number", (CLOSED,)).fetchall():
                    number, creator = row["number"], row["created_by"]
                    last = (json.loads(row["data"]).get("decisions") or [None])[-1]
                    found = self._decision(db, number, last)
                    if (found.get("decision") in FINISHING_DECISIONS and found.get("approver")
                            and str(found.get("reason") or "").strip()):
                        db.execute("UPDATE items SET status=?, updated_at=?, version=version+1 WHERE number=?",
                                   (FINISHED, self.now(), number))
                        self.write_journal(db, number, SYSTEM, SYSTEM, "migrated", {
                            "status": {"before": CLOSED, "after": FINISHED}, "decision": last,
                            "reason": "an approver's approval finishes a ticket (owner answer S-finish, "
                                      "build-plan section 29)"})
                    else:
                        self.write_journal(db, number, SYSTEM, SYSTEM, "notice",
                                           {"to": creator, "text": notice(number, creator)})
            db.execute(f"PRAGMA user_version={VERSION}")

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
                      details: Optional[dict] = None, *, at: Optional[str] = None) -> int:
        """One journal entry, stamped now, or at `at` (the sweep's date: it reads no clock)."""
        cursor = db.execute("INSERT INTO journal (item, actor, role, action, details, at) VALUES (?,?,?,?,?,?)",
                            (item, actor, role, action, _encode(details or {}), at or self.now()))
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

        `note` adds details to that entry, such as the reason a person gave. A finished task's status
        never changes again, and a task becomes finished only in an approver's update whose note
        names the decision it rests on (`_decided`), whatever path leads there (owner answer S-finish).
        Whatever path closes a task, a second entry follows the first: a notice to its creator, by
        `system`, that it is closed and what they may do (`notice`; owner answer S-closed).
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
        if "status" in changes:
            require(item["status"] != FINISHED, f"item_{FINISHED}",
                    f"#{number} is {FINISHED}: it stays {FINISHED}, with its whole history")
            if changes["status"] == FINISHED:
                require(item["status"] != CLOSED, f"item_{CLOSED}",
                        f"#{number} is {CLOSED}: it could not be finished, and does not reach the finished list")
                role = self.approver(db, actor)  # a worker, an agent or a service account never finishes
                self._decided(db, number, actor, (note or {}).get("decision"))
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
        ended = changes.get("status") in ENDS
        if ended and item["claimed_by"]:
            details["released"] = item["claimed_by"]  # a task whose work ends hands the claim back
        self.write_journal(db, number, actor, self.acting_role(db, actor, role), action, details)
        if ended:
            db.execute("UPDATE items SET claimed_by=NULL, lease_until=NULL WHERE number=?", (number,))
            if changes["status"] == CLOSED:
                self.write_journal(db, number, SYSTEM, SYSTEM, "notice",
                                   {"to": item["created_by"], "text": notice(number, item["created_by"])})
        elif self._holds(db, number, actor):
            self._renew(db, number)
        return self._item(db, number)

    def _decision(self, db, number: int, document) -> dict:
        """What a decision document about the task says (its data), or nothing if it is not one."""
        row = None
        if type(document) is int:
            row = db.execute("SELECT d.data FROM items d JOIN links l ON l.source=d.number AND l.type='about'"
                             " WHERE d.number=? AND d.kind='document' AND d.type='decision' AND l.target=?",
                             (document, number)).fetchone()
        return json.loads(row[0]) if row else {}

    def _decided(self, db, number: int, approver: str, decision) -> None:
        """Require the decision a task is finished on: a decision document about the task that this
        approver recorded, with a reason, approving it or finishing it (owner answer S-finish)."""
        found = self._decision(db, number, decision)
        require(found.get("approver") == approver and found.get("decision") in FINISHING_DECISIONS
                and str(found.get("reason") or "").strip() != "", "decision_required",
                f"#{number} is {FINISHED} only with a decision an approver records about it, with a reason")

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
        require(item["status"] not in ENDS, f"item_{item['status']}", f"#{number} is {item['status']}")
        if item["claimed_by"] == actor and not item["lease_active"]:
            raise RecordError("claim_expired", f"your lease on #{number} ran out at {item['lease_until']}; claim it again")
        require(item["claimed_by"] == actor, "claim_required", f"claim #{number} before changing it")
        self._renew(db, number)
        return self._item(db, number)

    def take(self, db, number: int, actor: str, role: Optional[str] = None) -> dict:
        """Claim inside an open transaction: free, expired, or already the actor's."""
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        require(item["status"] not in ENDS, f"item_{item['status']}", f"#{number} is {item['status']}")
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

    def release(self, number: int, actor: str, *, reason: Optional[str] = None) -> dict:
        with self.transaction() as db:
            return self.let_go(db, number, actor, reason=reason)

    def let_go(self, db, number: int, actor: str, *, reason: Optional[str] = None) -> dict:
        """Hand the claim back. A ticket released while `in_progress` has no decision yet, so it
        returns to `open` for the next handler (owner answer T-release, build-plan section 10); the
        journal entry records the change, and why when a reason is given, and the history stays.
        A parked ticket stays parked."""
        item = self._item(db, number)
        require(item["claimed_by"] == actor, "release_forbidden", f"only the holder can release #{number}")
        details = {} if reason is None else {"reason": text(reason, "reason")}
        if item["status"] == "in_progress":
            db.execute("UPDATE items SET status='open', claimed_by=NULL, lease_until=NULL, updated_at=?,"
                       " version=version+1 WHERE number=?", (self.now(), number))
            details["status"] = {"before": "in_progress", "after": "open"}
        else:
            db.execute("UPDATE items SET claimed_by=NULL, lease_until=NULL WHERE number=?", (number,))
        self.write_journal(db, number, actor, self.acting_role(db, actor), "released", details)
        return self._item(db, number)

    def open_ticket(self, number: int, actor: str, *, role: Optional[str] = None) -> dict:
        """Open a ticket: hand it to the actor (owner answers T-open and T-meaning, build-plan section 10).

        An open ticket is claimed by the actor and becomes `in_progress`, and the journal records
        who opened it and when. Opening a ticket that is already `in_progress` changes nothing. A
        ticket that waits on a decision, or whose work has ended (closed or finished), is not opened.
        """
        with self.transaction() as db:
            return self.opening(db, number, actor, role)

    def opening(self, db, number: int, actor: str, role: Optional[str] = None) -> dict:
        """`open_ticket` inside an open transaction."""
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        if item["status"] == "in_progress":
            return item
        require(item["status"] == "open", "not_open",
                f"#{number} is {item['status']}: only an open ticket is opened")
        self.take(db, number, actor, role)
        return self.update(db, number, actor, role=role, action="opened", status="in_progress")

    def resume(self, number: int, actor: str, *, role: Optional[str] = None) -> dict:
        """Take a ticket up again (owner answer P26, build-plan section 25).

        An open ticket (released without a decision, or sent back by an approver) and one still
        `in_progress` whose holder's lease ran out (Q-stale leaves its status) are handed to the
        actor: claimed, `in_progress`, and the journal records who resumed it. A ticket the actor
        already holds changes nothing, and one another holds on a live lease is refused. A ticket
        waiting on a decision is resumed once it is decided; a closed or finished ticket never is.
        """
        with self.transaction() as db:
            return self.resuming(db, number, actor, role)

    def resuming(self, db, number: int, actor: str, role: Optional[str] = None) -> dict:
        """`resume` inside an open transaction."""
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        require(item["status"] not in ENDS, f"item_{item['status']}",
                f"#{number} is {item['status']}: its work has stopped, so it is not resumed")
        require(item["status"] in ("open", "in_progress"), "not_open",
                f"#{number} is {item['status']}: it waits on a decision and is resumed only once that is made")
        if item["status"] == "in_progress" and item["claimed_by"] == actor and item["lease_active"]:
            return item
        self.take(db, number, actor, role)  # refuses another's live lease
        note = ({"previous": item["claimed_by"], "lease_ran_out": item["lease_until"]}
                if item["status"] == "in_progress" else {})
        return self.update(db, number, actor, role=role, action="resumed", note=note, status="in_progress")

    # -- what people do on a ticket -----------------------------------------------------------

    def set_status(self, number: int, actor: str, status: str, *, role: Optional[str] = None,
                   expected_version: Optional[int] = None) -> dict:
        with self.transaction() as db:
            self.hold(db, number, actor)
            return self.update(db, number, actor, role=role, expected_version=expected_version,
                               action="status_changed", status=status)

    def close(self, number: int, actor: str, reason: str) -> dict:
        """A worker closes a task that cannot be finished, with the reason (owner answers S-closed and
        S-close, build-plan sections 27 and 29).

        The worker holds the claim and acts in the worker role, and the reason is required. The journal
        records who closed it, when and why; the claim is handed back; and a notice on the ticket tells
        its creator that it is closed and that they may amend it and repost it, or delete it. A closed
        task is not claimed, opened, resumed or finished, and one nobody reacts to for
        CLOSED_RETENTION_DAYS is deleted by the sweep. A task waiting on a proposal is decided in the
        approval queue first; a task that may still be finished later is released instead (T-release).
        """
        with self.transaction() as db:
            return self.closing(db, number, actor, reason)

    def closing(self, db, number: int, actor: str, reason: str) -> dict:
        """`close` inside an open transaction."""
        reason = text(reason, "reason")
        item = self.hold(db, number, actor)  # the actor's live claim; refuses a task whose work has ended
        role = self.acting_role(db, actor, "worker")
        require(not item["data"].get("proposal"), "proposal_pending",
                f"#{number} waits on a proposal: an approver decides it first, in the approval queue")
        return self.update(db, number, actor, role=role, action=CLOSED, note={"reason": reason}, status=CLOSED)

    def finish(self, number: int, approver: str, decision: str) -> dict:
        """Finish a task: it is done and correct (owner answers S-finished and S-finish, build-plan
        sections 27 and 29).

        Only an approver finishes it, and only with a decision: a decision document about the task
        with the approver's name and ``decision``, the reason in the approver's words. The approver
        takes the claim for it, so another's live lease is respected, and the claim is handed back as
        the task is finished. A finished task stays finished and keeps its whole history. A task
        waiting on a proposal is decided in the approval queue instead, where an approval finishes it,
        and a task whose work has ended, closed or finished, is not finished.
        """
        decision = text(decision, "decision")
        with self.transaction() as db:
            return self.finishing(db, number, approver, decision)

    def finishing(self, db, number: int, approver: str, decision: str) -> dict:
        """`finish` inside an open transaction."""
        decision = text(decision, "decision")
        role = self.approver(db, approver)
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        require(not item["data"].get("proposal"), "proposal_pending",
                f"#{number} waits on a proposal: approve or reject it in the approval queue; an approval finishes it")
        self.take(db, number, approver, role)  # refuses a task whose work has ended, and another's live lease
        document = self.document(db, approver, "decision", f"Finished: #{number}",
                                 f"Finished by {approver} (approver): {decision}",
                                 data={"decision": FINISHED, "ticket": number, "approver": approver,
                                       "reason": decision},
                                 about=number, role=role)
        data = {**item["data"], "decisions": item["data"].get("decisions", []) + [document]}
        return self.update(db, number, approver, role=role, action=FINISHED,
                           note={"reason": decision, "decision": document}, data=data, status=FINISHED)

    # -- what the creator does with a closed ticket ----------------------------------------------

    def _created(self, db, number: int, actor: str) -> dict:
        """A closed task that the actor created: its creator is the item's `created_by` (owner answer
        S-closed, build-plan section 27: the creator amends and reposts it, or deletes it)."""
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        require(item["created_by"] == actor, "not_the_creator",
                f"#{number} was created by {item['created_by']}: only its creator does this")
        require(item["status"] == CLOSED, "not_closed",
                f"#{number} is {item['status']}: only a {CLOSED} ticket is amended, reposted or deleted by its creator")
        return item

    def amend(self, number: int, actor: str, *, title: Optional[str] = None, body: Optional[str] = None) -> dict:
        """The creator amends a closed ticket: a new title, a new body, or both (owner answer S-closed).

        Each amendment is one journal entry with the text before and after it. The ticket stays closed
        until its creator reposts it; nothing else about it changes.
        """
        fields = {}
        if title is not None:
            fields["title"] = text(title, "title", 200)
        if body is not None:
            fields["body"] = text(body, "body", 20_000)
        require(bool(fields), "invalid_argument", "an amendment gives a new title, a new body or both")
        with self.transaction() as db:
            item = self._created(db, number, actor)
            require(any(item[k] != v for k, v in fields.items()), "nothing_changed",
                    f"#{number} says that already: the amendment changes nothing")
            return self.update(db, number, actor, action="amended", **fields)

    def repost(self, number: int, actor: str) -> dict:
        """The creator reposts a closed ticket: it is open again, for the next handler, with its whole
        history kept, and the journal records the repost (owner answer S-closed). Refused unless the
        ticket is closed."""
        with self.transaction() as db:
            self._created(db, number, actor)
            return self.update(db, number, actor, action="reposted", status="open")

    # -- closed tickets are deleted in time ------------------------------------------------------

    def _last_reaction(self, db, number: int) -> Optional[datetime]:
        """When anyone last wrote on a ticket: its latest journal entry, or the latest on a document about
        it (a comment, an amendment, a finding about it, the notice to its creator)."""
        at = db.execute("SELECT MAX(at) FROM journal WHERE item = ? OR item IN"
                        " (SELECT source FROM links WHERE type = 'about' AND target = ?)", (number, number)).fetchone()[0]
        return datetime.fromisoformat(at) if at else None

    def _idle(self, db, number: int, cutoff: datetime) -> bool:
        """Whether a task is closed and nobody has written on it since `cutoff`."""
        row = db.execute("SELECT status FROM items WHERE number = ? AND kind = 'task'", (number,)).fetchone()
        last = self._last_reaction(db, number) if row is not None and row[0] == CLOSED else None
        return last is not None and last < cutoff

    def _closed_at(self, db, number: int) -> str:
        """When a closed task was closed: the latest journal entry that moved it to closed."""
        for at, details in db.execute("SELECT at, details FROM journal WHERE item = ? ORDER BY seq DESC", (number,)):
            status = json.loads(details).get("status")
            if isinstance(status, dict) and status.get("after") == CLOSED:
                return at
        return db.execute("SELECT updated_at FROM items WHERE number = ?", (number,)).fetchone()[0]

    def _delete(self, db, number: int, actor: str, role: str, at: str) -> None:
        """Delete a closed task inside an open transaction (owner answers S-del and S-keep, build-plan
        section 28). First one audit line: an entry on no item, with the task's number, when it was
        closed and when it is deleted, and no content. Then the task, its journal, its links, and the
        documents only about it, with their journals and links. The database refuses any row this does
        not mark in `deleting`, and any task that is not closed, and a row another kept record refers
        to (a schema version drafted on the ticket): the transaction is then rolled back whole."""
        documents = [r[0] for r in db.execute(
            "SELECT DISTINCT l.source FROM links l JOIN items d ON d.number = l.source"
            " WHERE l.type = 'about' AND l.target = ? AND d.kind = 'document' AND NOT EXISTS"
            " (SELECT 1 FROM links o WHERE o.source = l.source AND o.type = 'about' AND o.target != ?)",
            (number, number))]
        gone = [number, *documents]
        marks = _marks(gone)
        self.write_journal(db, None, actor, role, "deleted",
                           {"ticket": number, "closed_at": self._closed_at(db, number), "deleted_at": at}, at=at)
        db.executemany("INSERT INTO deleting (number) VALUES (?)", [(n,) for n in gone])
        db.execute(f"DELETE FROM journal WHERE item IN ({marks})", gone)
        db.execute(f"DELETE FROM links WHERE source IN ({marks}) OR target IN ({marks})", gone + gone)
        db.execute(f"DELETE FROM items WHERE number IN ({marks})", gone)
        db.execute("DELETE FROM deleting")

    def delete(self, number: int, actor: str) -> None:
        """The creator deletes a closed ticket now, the other choice it has besides amending and
        reposting it (owner answer S-closed, build-plan section 27): deleted as the sweep deletes one,
        with the same one audit line, attributed to the creator and stamped now. Refused unless the
        ticket is closed and the actor created it, and while a kept record still refers to it."""
        try:
            with self.transaction() as db:
                self._created(db, number, actor)
                self._delete(db, number, actor, self.acting_role(db, actor), self.now())
        except sqlite3.IntegrityError as error:
            if "FOREIGN KEY" not in str(error):
                raise
            raise RecordError("still_referred_to", f"#{number} stays: a kept record refers to it") from None

    def sweep(self, today) -> List[int]:
        """Delete every closed ticket nobody has reacted to for more than CLOSED_RETENTION_DAYS, and
        return their numbers (owner answers S-del, S-keep and S-period, build-plan sections 28 and 29).

        ``today`` is the date the sweep runs on: a date (taken at midnight UTC) or a datetime with its
        time zone. The sweep reads no clock, and nothing runs it but a call. A ticket's last reaction is
        the latest journal entry on it, or on a document about it (a comment, an amendment, a finding
        about it, the notice to its creator): the ticket is deleted once that is more than
        CLOSED_RETENTION_DAYS before
        ``today``, and kept until then. Each deletion is its own transaction, by `system`: one audit line
        (the ticket's number, when it was closed and when it was deleted, and no content), then the
        ticket, its journal and the documents only about it. A finished ticket is never deleted, however
        old. A closed ticket that a kept record still refers to (a schema version drafted on it) stays:
        the database refuses to delete it, and the sweep leaves it closed.
        """
        moment = _moment(today)
        stamp, cutoff = moment.isoformat(timespec="seconds"), moment - timedelta(days=CLOSED_RETENTION_DAYS)
        with self.reading() as db:
            closed = [r[0] for r in db.execute("SELECT number FROM items WHERE kind = 'task' AND status = ?"
                                               " ORDER BY number", (CLOSED,)).fetchall()]
            due = [number for number in closed if self._idle(db, number, cutoff)]
        deleted = []
        for number in due:
            try:
                with self.transaction() as db:
                    if not self._idle(db, number, cutoff):
                        continue  # someone wrote on it, or reposted it, since it was read above
                    self._delete(db, number, SYSTEM, SYSTEM, stamp)
            except sqlite3.IntegrityError as error:
                if "FOREIGN KEY" not in str(error):
                    raise
                continue  # a kept record still refers to it: the database keeps it, and so does the sweep
            deleted.append(number)
        return deleted

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
                f"                 WHERE l.target=i.number AND l.type='blocks' AND b.status NOT IN ({_marks(ENDS)}))"
                " ORDER BY number", ENDS).fetchall()
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

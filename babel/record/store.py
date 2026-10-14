"""Ticket spine: tasks and documents in one number space, leases, links and an attributed journal.

Modelled on Subroutine (github.com/simonholliday/subroutine), as the owner decided:

- one numbering scheme: a task and a document never share a number, and no number is reused;
- a decision or a finding is a document, which records what was concluded;
- a comment records what happened; comments and every state change are journal entries, and
  the journal is append-only (enforced by the database, not only by this code). The one exception
  is the owner's (S-del and S-keep, build-plan section 28): a closed ticket is deleted in time, its
  journal and the documents only about it with it, leaving one audit line without content;
- a `blocks` link keeps a task out of the ready list until its blocker is finished. A closed
  blocker went wrong, so it keeps blocking: until it is corrected, reposted and finished, or an
  approver's decision resolves or replaces the dependency; and while a task waits on it, it is not
  deleted (the owner's decision on R6-Q1, build-plan section 30);
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
- a worker closes a task that cannot be finished, with the reason (S-close, section 29). That is
  the only way a task is closed (the owner's decision on R6-Q4, section 30): every path to
  `closed` goes through `update`, which refuses a close that lacks the reason, the worker role or
  the worker's claim, and the database refuses a close the store has not marked with its actor
  and reason, and a task created closed or finished;
- a notice on a closed task tells the person who answers for it, its recipient: a person named
  when the task is created, by default its creator when the creator is a person, or else the
  approval queue, which approvers review; the task keeps its originator, a service or an agent
  too, as `created_by` (the owner's decision on R6-Q2, section 30). Its creator when a person, its
  recipient, or an approver for a task addressed to the approval queue, may amend its title or
  body, each amendment a journal entry with the text before and after, and repost it: open again,
  with its history; or delete it (S-closed, section 27). Each acts as themselves: a service or an
  agent never does, even on a task it created. A closed ticket no person reacts to for
  CLOSED_RETENTION_DAYS is deleted by the sweep, which runs only when called, on the date it is
  given (S-period, section 29); an entry by a service, an agent or `system` is no reaction (the
  owner's review of round six, section 30: REACTIONS).

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
from typing import Callable, Iterable, List, Optional, Tuple

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
#: what a decision document says when a task may be finished on it: an approval, a finish itself, or an
#: approver's drop of a file, a completed disposition (the owner's decision on R6-Q3, build-plan section 30)
FINISHING_DECISIONS = ("approved", "finished", "dropped")
#: the store's version, kept in SQLite's user_version; an older store is brought up to it once, when opened
VERSION = 5
DOCUMENT_TYPES = ("decision", "finding")
LINK_TYPES = ("blocks", "about")
LEASE = timedelta(days=1)  # from the holder's last write: the owner's answer to P22 (build-plan section 20)
#: how many days a closed ticket is kept after its last reaction; then the sweep deletes it, with its history
#: (owner answers S-del, S-keep and S-period, build-plan sections 28 and 29). A named setting
CLOSED_RETENTION_DAYS = 30
#: what a person writes that starts a closed ticket's CLOSED_RETENTION_DAYS again (the owner's review of round
#: six, build-plan section 30): on the ticket, a comment, an amendment or a repost; on a document about it, the
#: document itself (a decision or a finding) or a comment. Nothing a service, an agent or `system` writes counts,
#: nor a person's refused attempt (approval_refused, rejection_refused) or a link
REACTIONS = ("comment", "amended", "reposted")
DOCUMENT_REACTIONS = ("created", "comment")
SYSTEM = "system"
#: the recipient of a task that no named person answers for: the approval queue, which named people with the
#: approver role review (queue.py). An intake ticket goes there until real identities name the company's
#: responsible data owner (P6), and so does any task a service or an agent created (the owner's decision on
#: R6-Q2, build-plan section 30). It is not a user's name: add_user refuses it
REVIEW_QUEUE = "approval queue"
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
    version INTEGER NOT NULL,
    recipient TEXT);
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
CREATE TABLE IF NOT EXISTS closing (
    number INTEGER PRIMARY KEY,
    actor TEXT NOT NULL REFERENCES users(name),
    reason TEXT NOT NULL CHECK (trim(reason) != ''));
CREATE TRIGGER IF NOT EXISTS items_closed_with_a_reason BEFORE UPDATE OF status ON items
WHEN NEW.status = '{CLOSED}' AND OLD.status IS NOT '{CLOSED}'
     AND NOT EXISTS (SELECT 1 FROM closing WHERE number = NEW.number)
BEGIN SELECT RAISE(ABORT, 'a ticket is closed only by close(), which records who closed it and why'); END;
CREATE TRIGGER IF NOT EXISTS items_created_open BEFORE INSERT ON items
WHEN NEW.kind = 'task' AND NEW.status IN ('{CLOSED}', '{FINISHED}')
BEGIN SELECT RAISE(ABORT, 'a task is never created closed or finished: close() closes it, and only an approver finishes it'); END;
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
# `closing` holds the task the store closes, with who closes it and why, inside the transaction that
# closes it, and is empty at every other time: the close guard refuses any change to `closed` it does not
# name (the owner's decision on R6-Q4: no reasonless closure). Only update and the migration fill it.


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


def notice(number: int, recipient: str, creator: Optional[str] = None) -> str:
    """What the person who answers for a closed ticket is told (owner answer S-closed, build-plan section 27):
    its recipient, by name, or an approver, from the approval queue (the owner's decision on R6-Q2, section
    30). `creator` is the ticket's `created_by`; left out, the recipient is the creator."""
    if recipient == REVIEW_QUEUE:
        who = f"{creator} opened it and does not answer for it, so it is for the {REVIEW_QUEUE}: an approver may"
    elif creator in (None, recipient):
        who = f"{recipient}, as its creator you may"
    else:
        who = f"{recipient}, as the person who answers for it (it was opened by {creator}) you may"
    return (f"#{number} is closed: it could not be finished. {who} amend it and repost it, which opens it again "
            f"with its history, or delete it. If nobody reacts to it for {CLOSED_RETENTION_DAYS} days, it is "
            f"deleted, with its history.")


def _finishes(found: dict) -> Optional[str]:
    """Why an older store's closed ticket is finished on its last decision, or None (migration steps 3
    and 4): an approver's approval (owner answer S-finish, build-plan section 29), or a drop of a file by
    an approver, acting as one (the owner's decision on R6-Q3, section 30), each with a reason. Older
    code closed the ticket for both."""
    if not str(found.get("reason") or "").strip():
        return None
    if found.get("decision") in ("approved", FINISHED) and found.get("approver"):
        return "an approver's approval finishes a ticket (owner answer S-finish, build-plan section 29)"
    if found.get("decision") == "dropped" and found.get("role") == "approver" and found.get("by"):
        return ("an approver's drop of a file is a completed disposition (the owner's decision on R6-Q3, "
                "build-plan section 30)")
    return None


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
        4. An approver's drop of a file is a completed disposition (the owner's decision on R6-Q3,
           build-plan section 30). Older code closed the ticket of every drop. A closed ticket whose last
           decision is a drop by an approver, acting as one, with a reason, is finished, as step 3
           finishes an approval's; a drop by a worker stays closed. Steps 3 and 4 look at each closed
           ticket once, so a ticket they finish is never told it is closed.
        5. Notices reach a person who answers for the ticket (the owner's decision on R6-Q2, build-plan
           section 30). Every task gets its recipient as a new task does: its creator when a person,
           the approval queue otherwise. Done first, so that step 3 tells the recipient; it changes no
           status, title or body, so it writes no entry. A closed ticket whose last notice went to
           someone else (its creator, a service or an agent, which reads none) is told again, to its
           recipient, so its CLOSED_RETENTION_DAYS start when a person who can act on it is told.
        """
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version >= VERSION:
                return  # another connection brought it up while this one waited for the lock
            if version < 5:  # step 5, its first half: the recipient, before step 3 writes any notice
                if "recipient" not in {r["name"] for r in db.execute("PRAGMA table_info(items)")}:
                    db.execute("ALTER TABLE items ADD COLUMN recipient TEXT")
                db.execute("UPDATE items SET recipient = CASE WHEN (SELECT kind FROM users WHERE name = items.created_by)"
                           " = 'person' THEN created_by ELSE ? END WHERE kind = 'task' AND recipient IS NULL",
                           (REVIEW_QUEUE,))
            if version < 1:
                reason = "the status done is called closed (owner answer P25, build-plan section 25)"
                for (number,) in db.execute("SELECT number FROM items WHERE kind='task' AND status='done'"
                                            " ORDER BY number").fetchall():
                    # the close guard lets a ticket become closed only with its actor and reason marked
                    db.execute("INSERT INTO closing (number, actor, reason) VALUES (?,?,?)", (number, SYSTEM, reason))
                    db.execute("UPDATE items SET status=?, updated_at=?, version=version+1 WHERE number=?",
                               (CLOSED, self.now(), number))
                    db.execute("DELETE FROM closing WHERE number=?", (number,))
                    self.write_journal(db, number, SYSTEM, SYSTEM, "migrated", {
                        "status": {"before": "done", "after": CLOSED}, "reason": reason})
            if version < 2:
                db.execute("DROP TRIGGER IF EXISTS items_no_delete")
                db.execute("DROP TRIGGER IF EXISTS journal_no_delete")
            if version < 4:
                for row in db.execute("SELECT number, data, created_by, recipient FROM items WHERE kind='task'"
                                      " AND status=? ORDER BY number", (CLOSED,)).fetchall():
                    number = row["number"]
                    last = (json.loads(row["data"]).get("decisions") or [None])[-1]
                    why = _finishes(self._decision(db, number, last))
                    if why:  # steps 3 and 4
                        db.execute("UPDATE items SET status=?, updated_at=?, version=version+1 WHERE number=?",
                                   (FINISHED, self.now(), number))
                        self.write_journal(db, number, SYSTEM, SYSTEM, "migrated", {
                            "status": {"before": CLOSED, "after": FINISHED}, "decision": last, "reason": why})
                    elif version < 3:  # step 3: a store from version 3 on told the creator when it closed
                        self._notify(db, row)
            if version < 5:  # step 5, its second half: tell the recipient what no person was told
                for row in db.execute("SELECT number, created_by, recipient FROM items WHERE kind='task'"
                                      " AND status=? ORDER BY number", (CLOSED,)).fetchall():
                    told = db.execute("SELECT details FROM journal WHERE item=? AND action='notice'"
                                      " ORDER BY seq DESC LIMIT 1", (row["number"],)).fetchone()
                    if told is not None and json.loads(told[0]).get("to") != row["recipient"]:
                        self._notify(db, row)
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
        require(name != REVIEW_QUEUE, "invalid_argument", f"{name!r} is the approval queue's name, not a user's")
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

    def _recipient(self, db, kind: str, creator: str, recipient: Optional[str]) -> Optional[str]:
        """Who a task's notices go to (the owner's decision on R6-Q2, build-plan section 30): the person
        named, or the approval queue (REVIEW_QUEUE); by default its creator, when the creator is a person,
        and the approval queue when a service or an agent created it. A document has none."""
        if kind != "task":
            require(recipient is None, "invalid_argument", "only a task has a recipient")
            return None
        if recipient is None:
            return creator if self._user(db, creator)["kind"] == "person" else REVIEW_QUEUE
        if recipient != REVIEW_QUEUE:
            require(self._user(db, recipient)["kind"] == "person", "not_a_person",
                    f"{recipient} is not a person: a task's notices go to a person, or to the {REVIEW_QUEUE}")
        return recipient

    def create_item(self, db, actor: str, kind: str, type_: str, title: str, *, body: str = "",
                    data: Optional[dict] = None, status: str, origin: Optional[str] = None,
                    role: Optional[str] = None, recipient: Optional[str] = None) -> int:
        """Create a task or a document inside an open transaction. A task's `recipient` answers for it
        and gets its notices (`_recipient`); its creator stays `created_by`."""
        title = text(title, "title", 200)
        require(kind != "task" or status not in ENDS, "invalid_status",
                "a task is never created closed or finished: close() closes it, with its reason, and only an "
                "approver's decision finishes it")
        recipient = self._recipient(db, kind, actor, recipient)
        stamp = self.now()
        cursor = db.execute(
            "INSERT INTO items (kind, type, title, body, data, status, origin, created_by, created_at,"
            " updated_at, version, recipient) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
            (kind, type_, title, body, _encode(data or {}), status, origin, actor, stamp, stamp, recipient))
        number = cursor.lastrowid
        details = {"kind": kind, "type": type_, "title": title, "origin": origin}
        if kind == "task":
            details["recipient"] = recipient
        self.write_journal(db, number, actor, self.acting_role(db, actor, role), "created", details)
        return number

    def add_task(self, actor: str, title: str, *, body: str = "", data: Optional[dict] = None,
                 origin: Optional[str] = None, role: Optional[str] = None, recipient: Optional[str] = None) -> int:
        """Open a task. A task with the same origin is returned instead of a second one. `recipient` is
        the person who answers for it, or REVIEW_QUEUE; by default its creator, when a person."""
        with self.transaction() as db:
            if origin is not None:
                row = db.execute("SELECT number FROM items WHERE origin=?", (origin,)).fetchone()
                if row:
                    return row[0]
            return self.create_item(db, actor, "task", "task", title, body=body, data=data,
                                    status="open", origin=origin, role=role, recipient=recipient)

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

        `note` adds details to that entry, such as the reason a person gave. This is the boundary every
        change of a task's status goes through, whichever path asks for it. A finished task's status
        never changes again, and a task becomes finished only in an approver's update whose note
        names the decision it rests on (`_decided`; owner answer S-finish). A task becomes closed only
        in an update by a worker who holds its claim, whose note gives the reason (`_closer`; the
        owner's decision on R6-Q4), and the database refuses a close this has not marked. A second
        entry follows a close: a notice, by `system`, to the person who answers for the task, its
        recipient, that it is closed and what they may do (`_notify`; owner answer S-closed and the
        owner's decision on R6-Q2).
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
            elif changes["status"] == CLOSED:
                role = self._closer(db, item, actor, role, note)
        if not changes and not note:
            return item
        if changes:
            columns = {k: (_encode(v) if k == "data" else v) for k, v in changes.items()}
            assignments = ", ".join(f"{k}=?" for k in columns)
            closes = changes.get("status") == CLOSED
            if closes:  # the close guard's mark: who closes it, and why, for this transaction only
                db.execute("INSERT INTO closing (number, actor, reason) VALUES (?,?,?)",
                           (number, actor, note["reason"]))
            db.execute(f"UPDATE items SET {assignments}, updated_at=?, version=version+1 WHERE number=?",
                       (*columns.values(), self.now(), number))
            if closes:
                db.execute("DELETE FROM closing WHERE number=?", (number,))
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
                self._notify(db, item)
        elif self._holds(db, number, actor):
            self._renew(db, number)
        return self._item(db, number)

    def _notify(self, db, item) -> None:
        """The notice on a closed task, by `system`, to its recipient: the person who answers for it, or
        the approval queue (owner answer S-closed, build-plan section 27, and the owner's decision on
        R6-Q2, section 30)."""
        number, recipient = item["number"], item["recipient"]
        self.write_journal(db, number, SYSTEM, SYSTEM, "notice",
                           {"to": recipient, "text": notice(number, recipient, item["created_by"])})

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

    def _closer(self, db, item: dict, actor: str, role: Optional[str], note: Optional[dict]) -> str:
        """Require what every close needs, whatever path asks for it (owner answers S-close and S-closed,
        build-plan sections 27 and 29, and the owner's decision on R6-Q4, section 30): the reason, in the
        update's note; a worker, acting as one (an approver who decides, an agent without the worker
        role, a service account never closes); the worker's live claim; and no proposal waiting for an
        approver, who decides it first. Returns the role the close is taken in."""
        number = item["number"]
        reason = (note or {}).get("reason")
        require(isinstance(reason, str) and reason.strip() != "", "reason_required",
                f"#{number} is {CLOSED} only with a reason: close(number, actor, reason) records who closed it and why")
        role = self.acting_role(db, actor, role or "worker")
        require(role == "worker", "role_missing", f"a worker closes a ticket; {actor} acts as {role} here")
        if item["claimed_by"] == actor and not item["lease_active"]:
            raise RecordError("claim_expired", f"your lease on #{number} ran out at {item['lease_until']}; claim it again")
        require(item["claimed_by"] == actor, "claim_required", f"claim #{number} before closing it")
        require(not item["data"].get("proposal"), "proposal_pending",
                f"#{number} waits on a proposal: an approver decides it first, in the approval queue")
        return role

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
        """The holder changes a task's status. It never closes one: a close needs its reason, so the
        boundary (`update`) refuses it here, and close() is the way (the owner's decision on R6-Q4,
        build-plan section 30); nor does it finish one, which needs an approver's decision."""
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
        """`close` inside an open transaction. The boundary (`update`, `_closer`) checks the worker role,
        the claim and that no proposal waits; this checks the reason's text first."""
        reason = text(reason, "reason")
        self.hold(db, number, actor)  # the actor's live claim; refuses a task whose work has ended
        return self.update(db, number, actor, role="worker", action=CLOSED, note={"reason": reason}, status=CLOSED)

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

    # -- what the person who answers for a closed ticket does with it ------------------------------

    def _responsible(self, db, number: int, actor: str) -> Tuple[dict, str]:
        """A closed task the actor answers for, and the role the actor acts in (owner answer S-closed,
        build-plan section 27, and the owner's decision on R6-Q2, section 30). The actor is a person,
        acting as themselves: a service or an agent never is, even for a task it created. A person
        answers for a task as its creator or its recipient, in their own role, or, for a task addressed
        to the approval queue, as an approver, in that role."""
        item = self._item(db, number)
        require(item["kind"] == "task", "not_a_task", f"#{number} is a document")
        user = self._user(db, actor)
        require(user["kind"] == "person", "not_a_person",
                f"{actor} is {'an agent' if user['kind'] == 'agent' else 'a service account'}: a person who answers "
                f"for #{number} amends, reposts or deletes it, as themselves")
        if actor in (item["created_by"], item["recipient"]):
            role = self.acting_role(db, actor)
        elif item["recipient"] == REVIEW_QUEUE and "approver" in user["roles"]:
            role = self.approver(db, actor)
        else:
            who = (f"an approver, from the {REVIEW_QUEUE}" if item["recipient"] == REVIEW_QUEUE
                   else item["recipient"])
            raise RecordError("not_responsible", f"#{number} is answered for by {who}, not by {actor}")
        require(item["status"] == CLOSED, "not_closed",
                f"#{number} is {item['status']}: only a {CLOSED} ticket is amended, reposted or deleted")
        return item, role

    def amend(self, number: int, actor: str, *, title: Optional[str] = None, body: Optional[str] = None) -> dict:
        """The person who answers for a closed ticket amends it: a new title, a new body, or both (owner
        answer S-closed; who answers for it, `_responsible`).

        Each amendment is one journal entry with the text before and after it, by that person. The
        ticket stays closed until it is reposted; nothing else about it changes.
        """
        fields = {}
        if title is not None:
            fields["title"] = text(title, "title", 200)
        if body is not None:
            fields["body"] = text(body, "body", 20_000)
        require(bool(fields), "invalid_argument", "an amendment gives a new title, a new body or both")
        with self.transaction() as db:
            item, role = self._responsible(db, number, actor)
            require(any(item[k] != v for k, v in fields.items()), "nothing_changed",
                    f"#{number} says that already: the amendment changes nothing")
            return self.update(db, number, actor, role=role, action="amended", **fields)

    def repost(self, number: int, actor: str) -> dict:
        """The person who answers for a closed ticket reposts it: it is open again, for the next handler,
        with its whole history kept, and the journal records the repost by that person (owner answer
        S-closed; who answers for it, `_responsible`). Refused unless the ticket is closed."""
        with self.transaction() as db:
            _, role = self._responsible(db, number, actor)
            return self.update(db, number, actor, role=role, action="reposted", status="open")

    def notices(self, recipient: str) -> List[dict]:
        """The closed tasks whose notices go to `recipient`, a person or REVIEW_QUEUE, oldest first: what
        they are asked to react to, each with its number, title, creator and the text of its last notice
        (the owner's decision on R6-Q2, build-plan section 30)."""
        with self.reading() as db:
            rows = db.execute("SELECT number, title, created_by FROM items WHERE kind = 'task' AND status = ?"
                              " AND recipient = ? ORDER BY number", (CLOSED, recipient)).fetchall()
            told = [db.execute("SELECT details FROM journal WHERE item = ? AND action = 'notice' ORDER BY seq DESC"
                               " LIMIT 1", (row["number"],)).fetchone() for row in rows]
        return [{"number": row["number"], "title": row["title"], "created_by": row["created_by"],
                 "notice": json.loads(last[0])["text"] if last else None} for row, last in zip(rows, told)]

    # -- closed tickets are deleted in time ------------------------------------------------------

    def _last_reaction(self, db, number: int) -> datetime:
        """When a closed ticket's CLOSED_RETENTION_DAYS last started (the owner's review of round six,
        build-plan section 30): when the person who answers for it was told it is closed (its last
        notice, or its last close if it has none), or a person's later reaction, whichever is latest.
        A reaction is what a person writes: on the ticket, a comment, an amendment or a repost
        (REACTIONS); about it, a decision or a finding, or a comment on one (DOCUMENT_REACTIONS).
        Nothing else restarts it: no entry by a service, an agent or `system`, and no refused attempt,
        so no automated write postpones a deletion."""
        told = db.execute("SELECT MAX(at) FROM journal WHERE item = ? AND (action = 'notice'"
                          " OR json_extract(details, '$.status.after') = ?)", (number, CLOSED)).fetchone()[0]
        reacted = db.execute(
            "SELECT MAX(j.at) FROM journal j JOIN users u ON u.name = j.actor WHERE u.kind = 'person' AND"
            f" ((j.item = ? AND j.action IN ({_marks(REACTIONS)})) OR (j.action IN ({_marks(DOCUMENT_REACTIONS)})"
            " AND j.item IN (SELECT source FROM links WHERE type = 'about' AND target = ?)))",
            (number, *REACTIONS, *DOCUMENT_REACTIONS, number)).fetchone()[0]
        at = max((stamp for stamp in (told, reacted) if stamp), default=None)
        if at is None:  # a close no entry records, as tests and older code may have left one
            at = db.execute("SELECT updated_at FROM items WHERE number = ?", (number,)).fetchone()[0]
        return datetime.fromisoformat(at)

    def _idle(self, db, number: int, cutoff: datetime) -> bool:
        """Whether a task is closed and its CLOSED_RETENTION_DAYS last started before `cutoff`."""
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

    def _blocking(self, db, number: int) -> List[int]:
        """The tasks that wait on this one: those it blocks that are not finished. A closed task keeps
        them waiting (the owner's decision on R6-Q1, build-plan section 30)."""
        return [r[0] for r in db.execute(
            "SELECT l.target FROM links l JOIN items t ON t.number = l.target"
            " WHERE l.source = ? AND l.type = 'blocks' AND t.status != ? ORDER BY l.target", (number, FINISHED))]

    def _due(self, db, number: int, cutoff: datetime) -> bool:
        """Whether the sweep deletes a task now: closed, nobody has reacted to it since `cutoff`, and no
        task waits on it."""
        return self._idle(db, number, cutoff) and not self._blocking(db, number)

    def _delete(self, db, number: int, actor: str, role: str, at: str) -> None:
        """Delete a closed task inside an open transaction (owner answers S-del and S-keep, build-plan
        section 28). First one audit line: an entry on no item, with the task's number, when it was
        closed and when it is deleted, and no content. Then the task, its journal, its links, and the
        documents only about it, with their journals and links. A task that another task still waits on
        is refused, so no unresolved blocker goes silently with it (the owner's decision on R6-Q1). The
        database refuses any row this does not mark in `deleting`, and any task that is not closed, and
        a row another kept record refers to (a schema version drafted on the ticket): the transaction is
        then rolled back whole."""
        waiting = self._blocking(db, number)
        require(not waiting, "still_blocking",
                f"#{number} stays: {', '.join(f'#{n}' for n in waiting)} waits on it, until it is reposted and "
                f"finished or an approver resolves the dependency")
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
        """The person who answers for a closed ticket deletes it now, the other choice besides amending
        and reposting it (owner answer S-closed, build-plan section 27; who answers for it,
        `_responsible`): deleted as the sweep deletes one, with the same one audit line, attributed to
        that person and stamped now. Refused unless the ticket is closed and the actor answers for it,
        while a task still waits on it (still_blocking), and while a kept record still refers to it."""
        try:
            with self.transaction() as db:
                _, role = self._responsible(db, number, actor)
                self._delete(db, number, actor, role, self.now())
        except sqlite3.IntegrityError as error:
            if "FOREIGN KEY" not in str(error):
                raise
            raise RecordError("still_referred_to", f"#{number} stays: a kept record refers to it") from None

    def sweep(self, today) -> List[int]:
        """Delete every closed ticket nobody has reacted to for more than CLOSED_RETENTION_DAYS, and
        return their numbers (owner answers S-del, S-keep and S-period, build-plan sections 28 and 29).

        ``today`` is the date the sweep runs on: a date (taken at midnight UTC) or a datetime with its
        time zone. The sweep reads no clock, and nothing runs it but a call. A ticket's days start when
        the person who answers for it is told it is closed, and again with each reaction by a person (a
        comment, an amendment, a repost; a decision or a finding about it, or a comment on one); an
        entry by a service, an agent or `system` is no reaction (`_last_reaction`). The ticket is deleted
        once its days started more than CLOSED_RETENTION_DAYS before ``today``, and kept until then. Each
        deletion is its own
        transaction, by `system`: one audit line (the ticket's number, when it was closed and when it
        was deleted, and no content), then the ticket, its journal and the documents only about it. A
        finished ticket is never deleted, however old. A closed ticket that an unfinished task still
        waits on (it blocks it) stays, closed and blocking, until it is reposted and finished or an
        approver resolves the dependency (the owner's decision on R6-Q1); the sweep tries again on its
        next run. A closed ticket that a kept record still refers to (a schema version drafted on it)
        stays: the database refuses to delete it, and the sweep leaves it closed.
        """
        moment = _moment(today)
        stamp, cutoff = moment.isoformat(timespec="seconds"), moment - timedelta(days=CLOSED_RETENTION_DAYS)
        with self.reading() as db:
            closed = [r[0] for r in db.execute("SELECT number FROM items WHERE kind = 'task' AND status = ?"
                                               " ORDER BY number", (CLOSED,)).fetchall()]
            due = [number for number in closed if self._due(db, number, cutoff)]
        deleted = []
        for number in due:
            try:
                with self.transaction() as db:
                    if not self._due(db, number, cutoff):
                        continue  # someone wrote on it, reposted it or made it block a task since it was read
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

    def resolve_dependency(self, dependent: int, blocker: int, approver: str, reason: str, *,
                           replacement: Optional[int] = None) -> dict:
        """An approver decides a dependency whose blocker is not finished (the owner's decision on R6-Q1,
        build-plan section 30): the dependent task no longer waits on the blocker (resolved), or waits
        on `replacement` instead (replaced).

        Without such a decision a task waits until its blocker is finished, a closed blocker corrected,
        reposted and worked first. Only a named person with the approver role decides, with a reason.
        The decision is a document about the dependent task, naming the blocker, the replacement if
        any, the approver and the reason; the `blocks` link goes, the replacement's is made, and the
        dependent's journal records the decision. Neither task's status changes. A closed blocker that
        nothing waits on any more is deleted in time, like any closed ticket.
        """
        reason = text(reason, "reason")
        with self.transaction() as db:
            role = self.approver(db, approver)  # a worker, an agent or a service account never decides it
            found = db.execute("SELECT b.status FROM links l JOIN items b ON b.number = l.source"
                               " WHERE l.source = ? AND l.type = 'blocks' AND l.target = ?",
                               (blocker, dependent)).fetchone()
            require(found is not None and found[0] != FINISHED, "not_blocked",
                    f"#{dependent} does not wait on #{blocker}: there is no dependency to decide")
            require(replacement not in (blocker, dependent), "invalid_argument",
                    "a replacement is another task than the blocker and the task that waits")
            resolution = "resolved" if replacement is None else "replaced"
            said = (f"#{dependent} no longer waits on #{blocker}" if replacement is None
                    else f"#{dependent} waits on #{replacement} instead of #{blocker}")
            document = self.document(
                db, approver, "decision", f"Dependency {resolution}: #{dependent} on #{blocker}",
                f"{said}, as {approver} (approver) decided: {reason}",
                data={"decision": f"dependency_{resolution}", "ticket": dependent, "blocker": blocker,
                      "replacement": replacement, "approver": approver, "reason": reason},
                about=dependent, role=role)
            db.execute("DELETE FROM links WHERE source = ? AND type = 'blocks' AND target = ?", (blocker, dependent))
            details = {"blocker": blocker, "decision": document, "reason": reason}
            if replacement is not None:
                self._link(db, approver, replacement, "blocks", dependent, role)
                details["replacement"] = replacement
            self.write_journal(db, dependent, approver, role, f"dependency_{resolution}", details)
            return self._item(db, dependent)

    def ready(self, actor: Optional[str] = None) -> List[dict]:
        """Tasks someone can start: open or in progress, every blocker finished (a closed one keeps
        blocking: the owner's decision on R6-Q1, build-plan section 30), not held by another."""
        with self.reading() as db:
            rows = db.execute(
                "SELECT number FROM items i WHERE kind='task' AND status IN ('open','in_progress')"
                " AND NOT EXISTS (SELECT 1 FROM links l JOIN items b ON b.number=l.source"
                "                 WHERE l.target=i.number AND l.type='blocks' AND b.status != ?)"
                " ORDER BY number", (FINISHED,)).fetchall()
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

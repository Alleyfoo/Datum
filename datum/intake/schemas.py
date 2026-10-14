"""Schema versions: a company's header declaration for one file kind, versioned.

A version number is allocated once per company and file kind, when a draft is made, and is never
reused. A version is never rewritten: its declaration cannot change and it is never deleted (the
database refuses both), so a change is always a new version. Only the status moves, and only
forward: a draft becomes active or rejected, and an active version becomes superseded when a newer
one is activated. At most one version per company and file kind is active.

An amendment is a new version (owner answer P23, build-plan section 7). A file accepted under an
earlier version stays accepted under that version, and the new version is not checked against it;
the amendment applies to new files.

Drafting is open to anyone with access to the company's folder (build-plan section 7): whoever
holds the ticket's claim and acts in a role (worker or approver) drafts, and the draft records who
drafted it. A service account, such as the hook, never drafts: it holds no role, and modules write
only to the inbox. The draft's full rule list is written onto the ticket, and the draft is proposed
to an approver as create_schema. Activation is the create-schema gate, confirm(): nothing else
activates a version, neither a timeout nor the hook.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Callable, List, Optional, Tuple

from datum.record import queue
from datum.record.store import ROLES, Store, require, text
from datum.schema.headers import Column, HeaderSchema, Versioned

from . import cleaning, staging, trial
from .staging import Dataset

FILE_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}")
STATUSES = ("draft", "active", "superseded", "rejected")

TABLE = """
CREATE TABLE IF NOT EXISTS schema_versions (
    company_id TEXT NOT NULL,
    file_kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    declaration TEXT NOT NULL,
    digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'superseded', 'rejected')),
    ticket INTEGER NOT NULL REFERENCES items(number),
    drafted_from TEXT NOT NULL,
    drafted_by TEXT NOT NULL REFERENCES users(name),
    drafted_at TEXT NOT NULL,
    decided_by TEXT REFERENCES users(name),
    decided_at TEXT,
    reason TEXT,
    PRIMARY KEY (company_id, file_kind, version));
CREATE UNIQUE INDEX IF NOT EXISTS schema_versions_one_active
    ON schema_versions (company_id, file_kind) WHERE status = 'active';
CREATE TRIGGER IF NOT EXISTS schema_versions_never_rewritten
BEFORE UPDATE OF company_id, file_kind, version, declaration, digest, ticket, drafted_from,
                 drafted_by, drafted_at ON schema_versions
BEGIN SELECT RAISE(ABORT, 'a schema version is never rewritten; draft a new version'); END;
CREATE TRIGGER IF NOT EXISTS schema_versions_decided_once
BEFORE UPDATE OF decided_by, decided_at, reason ON schema_versions WHEN OLD.decided_by IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a schema version is decided once'); END;
CREATE TRIGGER IF NOT EXISTS schema_versions_status_forward
BEFORE UPDATE OF status ON schema_versions
WHEN NOT ((OLD.status = 'draft' AND NEW.status IN ('active', 'rejected'))
          OR (OLD.status = 'active' AND NEW.status = 'superseded'))
BEGIN SELECT RAISE(ABORT, 'a schema version status only moves forward'); END;
CREATE TRIGGER IF NOT EXISTS schema_versions_no_delete BEFORE DELETE ON schema_versions
BEGIN SELECT RAISE(ABORT, 'a schema version is never deleted'); END;
"""


def ready(store: Store) -> None:
    store.ensure(TABLE)


def _row(row) -> dict:
    found = dict(row)
    found["schema"] = HeaderSchema.from_dict(json.loads(found.pop("declaration")))
    return found


def get(store: Store, company_id: str, file_kind: str, version: int) -> dict:
    ready(store)
    with store.reading() as db:
        row = db.execute("SELECT * FROM schema_versions WHERE company_id=? AND file_kind=? AND version=?",
                         (company_id, file_kind, version)).fetchone()
    require(row is not None, "unknown_version", f"{company_id} has no {file_kind} version {version}")
    return _row(row)


def versions(store: Store, company_id: str, file_kind: str) -> List[dict]:
    ready(store)
    with store.reading() as db:
        rows = db.execute("SELECT * FROM schema_versions WHERE company_id=? AND file_kind=? ORDER BY version",
                          (company_id, file_kind)).fetchall()
    return [_row(r) for r in rows]


def active(store: Store, company_id: str) -> List[Versioned]:
    """The active version of each file kind of a company: what the hook tries a file against."""
    ready(store)
    with store.reading() as db:
        rows = db.execute("SELECT * FROM schema_versions WHERE company_id=? AND status='active'"
                          " ORDER BY file_kind", (company_id,)).fetchall()
    return [Versioned(r["company_id"], r["file_kind"], r["version"], _row(r)["schema"]) for r in rows]


def provider(store: Store) -> Callable[[str], List[Versioned]]:
    return lambda company_id: active(store, company_id)


def current_version(db, company_id: str, file_kind: str) -> Optional[int]:
    """The active version number inside an open transaction; None if this store holds no versions
    of the kind (the schemas then came from another provider)."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_versions'").fetchone() is None:
        return None
    if db.execute("SELECT 1 FROM schema_versions WHERE company_id=? AND file_kind=?",
                  (company_id, file_kind)).fetchone() is None:
        return None
    row = db.execute("SELECT version FROM schema_versions WHERE company_id=? AND file_kind=? AND status='active'",
                     (company_id, file_kind)).fetchone()
    return row[0] if row else 0


def suggest(dataset: Dataset, header_row: int = 1) -> Tuple[Optional[HeaderSchema], List[dict]]:
    """A draft read off a staged sheet, with the evidence for each column, for a worker to check.

    The sheet is read as the default rules (F1, T1) leave it, since a trial will see it that way:
    a formula counts as the value the file saved for it, header names come trimmed, and a text of
    only whitespace counts as empty. A column's type is proposed only when every value below the
    header row has the same kind (a formula with no saved value has none, so its column stays
    undecided); a column that is ever empty is proposed as optional. With any column undecided
    there is no draft, only the evidence. No case is proposed: a declared transformation is a
    person's choice.
    """
    dataset = cleaning.clean([dataset]).datasets[0]
    header = dataset.row(header_row)
    evidence, columns = [], []
    if header is None:
        return None, evidence
    for ordinal in range(1, dataset.width + 1):
        name, code = header.texts[ordinal - 1], header.codes[ordinal - 1]
        cells = [(r.texts[ordinal - 1], r.codes[ordinal - 1]) for r in dataset.rows[header_row:] if not r.blank]
        kinds = Counter(c for _, c in cells)
        present = [(t, c) for t, c in cells if c != "e"]
        proposed = None
        if code == "s" and present:
            found = {c for _, c in present}
            if found == {"s"}:
                proposed = "text"
            elif found == {"n"}:
                proposed = "int" if all(re.fullmatch(r"-?\d+", t) for t, _ in present) else "decimal"
            elif found == {"b"}:
                proposed = "bool"
            elif found == {"d"}:
                proposed = "date" if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}(T00:00:00)?", t) for t, _ in present) else "datetime"
        evidence.append({"column": f"c{ordinal:03d}", "header": name if code == "s" else None,
                         "codes": dict(sorted(kinds.items())), "proposed": proposed})
        if proposed:
            columns.append(Column(name, proposed, required="e" not in kinds))
    if len(columns) != dataset.width or not columns:
        return None, evidence
    return HeaderSchema(dataset.sheet, header_row, tuple(columns)), evidence


def draft(store: Store, ticket: int, actor: str, file_kind: str, schema: HeaderSchema, reason: str) -> Versioned:
    """Whoever holds the ticket, in any role, drafts the next version from the ticket's file, lists
    its rules on the ticket and proposes it to an approver. The draft records who drafted it."""
    ready(store)
    reason = text(reason, "reason")
    require(isinstance(file_kind, str) and FILE_KIND.fullmatch(file_kind) is not None, "invalid_argument",
            "a file kind is lower-case letters, digits and underscores, starting with a letter")
    with store.transaction() as db:
        item = store.hold(db, ticket, actor)
        role = store.acting_role(db, actor)
        require(role in ROLES, "role_missing",
                f"{actor} is a service account and holds no role; a draft is made by a person or an "
                "assistant with access to the company's folder")
        require(not item["data"].get("proposal"), "proposal_pending", f"#{ticket} already waits on a decision")
        subject = item["data"].get("subject") or {}
        require(subject.get("company_id") and subject.get("source_id"), "invalid_argument",
                f"#{ticket} does not name the file a schema would be drafted from")
        company_id = subject["company_id"]
        version = db.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM schema_versions WHERE company_id=?"
                             " AND file_kind=?", (company_id, file_kind)).fetchone()[0]
        db.execute("INSERT INTO schema_versions (company_id, file_kind, version, declaration, digest, status,"
                   " ticket, drafted_from, drafted_by, drafted_at) VALUES (?,?,?,?,?,'draft',?,?,?,?)",
                   (company_id, file_kind, version, json.dumps(schema.to_dict(), ensure_ascii=False, sort_keys=True),
                    schema.digest(), ticket, subject["source_id"], actor, store.now()))
        store.write_journal(db, ticket, actor, role, "rules_listed", {
            "company_id": company_id, "file_kind": file_kind, "version": version, "digest": schema.digest(),
            "rules": schema.rule_text()})
    queue.propose(store, ticket, actor, "create_schema", reason, role=role,
                  payload={"company_id": company_id, "file_kind": file_kind, "version": version})
    return Versioned(company_id, file_kind, version, schema)


# -- the create-schema gate ----------------------------------------------------------------------

def rules_on_ticket(db, ticket: int, version: dict) -> bool:
    """Whether the ticket carries the draft's full rule list, as written when it was drafted."""
    for row in db.execute("SELECT details FROM journal WHERE item=? AND action='rules_listed' ORDER BY seq",
                          (ticket,)):
        listed = json.loads(row[0])
        if (listed.get("company_id"), listed.get("file_kind"), listed.get("version")) == (
                version["company_id"], version["file_kind"], version["version"]):
            return listed.get("digest") == version["digest"] and listed.get("rules") == version["schema"].rule_text()
    return False


def _sheets(root, company_id: str, source_id: str) -> List[Dataset]:
    return staging.datasets(root, company_id, source_id) or staging.stage_all(root, company_id, source_id)


def _draft(db, payload: dict) -> dict:
    row = db.execute("SELECT * FROM schema_versions WHERE company_id=? AND file_kind=? AND version=?",
                     (payload["company_id"], payload["file_kind"], payload["version"])).fetchone()
    require(row is not None and row["status"] == "draft", "not_a_draft",
            f"{payload['file_kind']} version {payload['version']} is not a draft waiting for a decision")
    return _row(row)


def confirm(store: Store, root, ticket: int, approver: str, reason: str) -> dict:
    """The create-schema gate: an approver confirms the draft the ticket proposes.

    The draft becomes active only when all of these hold, checked in the approval's transaction:
    1. a named person who holds the approver role, whose name is not agent-like, confirms it with a
       reason (the confirmer may be the drafter: owner answers Q7 and round two);
    2. the draft's full rule list is on the ticket, as written when it was drafted;
    3. the file it was drafted from, cleaned for the draft (its change records stored), passes it
       with zero refusals.
    Files the company already accepted are not checked: each stays accepted under the version it was
    accepted with, and the new version applies to new files (owner answer P23). Otherwise nothing
    changes, the refusal is journaled, and the version stays a draft. On success the previous active
    version is superseded, the ticket's file gets a new verified trial finding, and its import is
    proposed to an approver.
    """
    ready(store)

    def gate(db, item, proposal):
        version = _draft(db, proposal["payload"])
        company_id, file_kind, number = version["company_id"], version["file_kind"], version["version"]
        schema, label = version["schema"], f"schema {file_kind} v{number}"
        require(rules_on_ticket(db, item["number"], version), "rules_not_on_ticket",
                f"#{item['number']} does not carry the full rule list of {label}")
        sheets = _sheets(root, company_id, version["drafted_from"])
        cleaned = cleaning.clean(sheets, schema)
        cleaning.record(root, company_id, cleaned)
        own = trial.run(cleaned.datasets, schema)
        require(own.fits, "draft_refuses_its_file",
                f"{label} does not pass the file it was drafted from: {trial.headline(own)}")
        check = trial.verify(root, company_id, version["drafted_from"], sheets, schema, own)
        require(check["fingerprints_reproduced"] and check["trial_reproduced"], "not_reproduced",
                f"the trial of the drafted file against {label} did not reproduce from the raw file")

        stamp = store.now()
        db.execute("UPDATE schema_versions SET status='superseded' WHERE company_id=? AND file_kind=?"
                   " AND status='active'", (company_id, file_kind))
        db.execute("UPDATE schema_versions SET status='active', decided_by=?, decided_at=?, reason=?"
                   " WHERE company_id=? AND file_kind=? AND version=?",
                   (approver, stamp, reason, company_id, file_kind, number))
        subject = item["data"]["subject"]
        finding = store.document(
            db, approver, "finding", f"Trial against {label}: {trial.headline(own)}",
            trial.report(own, schema) + "\n\n" + cleaning.report(cleaned) + "\n\nVerified: every sheet "
            "rebuilt from the raw file gives its staged fingerprint, and the rebuilt sheets, cleaned and "
            f"tried again, give the same result (digest {check['result_digest'][:16]}).",
            data={**own.to_dict(), "subject": subject, "file_kind": file_kind, "schema_version": number,
                  "cleaning": cleaned.summary(), "verification": check},
            about=item["number"], role="approver")
        name = subject.get("original_name", subject["source_id"])
        return {
            "title": f"{name}: fits {label}: ready to import",
            "data": {"trial": {"outcome": "fits", "finding": finding, "file_kind": file_kind,
                               "schema_version": number},
                     "choices": ["import", "drop"]},
            "proposal": {"action": "import", "reason": f"The file fits {label} with zero refusals.",
                         "payload": {"company_id": company_id, "source_id": subject["source_id"],
                                     "file_kind": file_kind, "schema_version": number, "finding": finding}},
            "record": {"schema": {"company_id": company_id, "file_kind": file_kind, "version": number,
                                  "digest": version["digest"]},
                       "gate": {"rules_on_ticket": True, "drafted_from": version["drafted_from"],
                                "drafted_from_refusals": 0}},
            "summary": (f"Gate passed: the full rule list is on the ticket; the drafted file passes with "
                        f"zero refusals. {label} is active. Files accepted under earlier versions keep "
                        f"their versions and were not checked against it."),
        }

    return queue.approve(store, ticket, approver, reason, effect=gate, expect="create_schema")


def refuse(store: Store, ticket: int, approver: str, reason: str) -> dict:
    """An approver turns the draft down: it is marked rejected, keeps its number, and the ticket
    goes back to the workers."""
    ready(store)

    def rejected(db, item, proposal):
        version = _draft(db, proposal["payload"])
        db.execute("UPDATE schema_versions SET status='rejected', decided_by=?, decided_at=?, reason=?"
                   " WHERE company_id=? AND file_kind=? AND version=?",
                   (approver, store.now(), reason, version["company_id"], version["file_kind"], version["version"]))
        return {"record": {"schema": {"company_id": version["company_id"], "file_kind": version["file_kind"],
                                      "version": version["version"], "status": "rejected"}}}

    return queue.reject(store, ticket, approver, reason, effect=rejected, expect="create_schema")

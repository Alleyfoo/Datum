"""Dispositions: what a person decides about an arriving file. There are three.

- import: the file fits an active schema, and an approver admits it. Admission records the file
  as accepted for its company and file kind under that schema version (see accepted.py).
- create_schema: the file needs a schema, or a new version of one. A worker drafts it and an
  approver confirms it; the confirmation is the create-schema gate (schemas.py).
- drop: the file is not needed. A worker or an approver drops it with a reason. It stays in the
  inbox and the ticket records that it was dropped and why; nothing is deleted.

A worker can drop; an approver is needed to admit. Each decision is a document about the ticket
and every step is a journal entry. Writing admitted rows to extracts/ (Publish) is not built yet.

An import names the trial finding it rests on: a finding about the same ticket that says the file
fits that file kind and schema version. Proposing and admitting both check it, so nothing is
admitted without a verified fit.
"""

from __future__ import annotations

from typing import Optional

from babel.record import queue
from babel.record.store import Store, require, text

from . import accepted, schemas

DISPOSITIONS = ("import", "create_schema", "drop")
#: what a proposal of each kind must name
PAYLOAD = {
    "import": ("company_id", "source_id", "file_kind", "schema_version", "finding"),
    "create_schema": ("company_id", "file_kind", "version"),
}


def fitting_finding(store: Store, db, ticket: int, payload: dict) -> dict:
    """The finding an import rests on: about this ticket, saying this file fits this version."""
    number = payload.get("finding")
    row = db.execute("SELECT 1 FROM links l JOIN items f ON f.number=l.source WHERE l.source=? AND"
                     " l.type='about' AND l.target=? AND f.type='finding'", (number, ticket)).fetchone()
    data = store._item(db, number)["data"] if row else {}
    subject = data.get("subject") or {}
    fits = (data.get("outcome") == "fits" and data.get("file_kind") == payload.get("file_kind")
            and data.get("schema_version") == payload.get("schema_version")
            and subject.get("source_id") == payload.get("source_id")
            and subject.get("company_id") == payload.get("company_id"))
    require(fits, "no_fitting_trial", f"#{ticket} has no trial finding saying {payload.get('source_id')} fits "
                                      f"{payload.get('file_kind')} version {payload.get('schema_version')}")
    return data


def drop(store: Store, ticket: int, actor: str, reason: str, *, role: Optional[str] = None) -> dict:
    """A worker or an approver drops the file. The ticket is done; the file stays where it is."""
    reason = text(reason, "reason")
    with store.transaction() as db:
        item = store.hold(db, ticket, actor)
        acting = store.acting_role(db, actor, role)
        require(acting in ("worker", "approver"), "role_missing", "a worker or an approver drops a file")
        decision = store.document(
            db, actor, "decision", f"Dropped: #{ticket}",
            f"Dropped by {actor} ({acting}): {reason}\nThe file stays in the inbox; nothing is deleted.",
            data={"decision": "dropped", "disposition": "drop", "ticket": ticket, "by": actor,
                  "role": acting, "reason": reason, "subject": item["data"].get("subject")},
            about=ticket, role=acting)
        data = {k: v for k, v in item["data"].items() if k != "proposal"}
        data.update(resolution="dropped", decisions=data.get("decisions", []) + [decision])
        return store.update(db, ticket, actor, role=acting, action="dropped",
                            note={"reason": reason, "decision": decision}, data=data, status="done")


def propose(store: Store, ticket: int, actor: str, disposition: str, reason: str, *, payload: dict,
            role: Optional[str] = None) -> dict:
    """Ask an approver for an import or a new schema. Dropping needs no approver: use drop()."""
    require(disposition in PAYLOAD, "invalid_disposition",
            f"an approver decides {sorted(PAYLOAD)}; the dispositions are {DISPOSITIONS}")
    missing = [key for key in PAYLOAD[disposition] if payload.get(key) in (None, "")]
    require(not missing, "invalid_argument", f"a {disposition} proposal must name {', '.join(missing)}")
    if disposition == "import":
        with store.reading() as db:
            fitting_finding(store, db, ticket, payload)
    return queue.propose(store, ticket, actor, disposition, reason, payload=payload, role=role)


def admit(store: Store, ticket: int, approver: str, reason: str) -> dict:
    """An approver admits the file an import proposal names: it becomes an accepted file."""
    accepted.ready(store)

    def effect(db, item, proposal):
        p = proposal["payload"]
        fitting_finding(store, db, item["number"], p)
        current = schemas.current_version(db, p["company_id"], p["file_kind"])
        require(current is None or current == p["schema_version"], "schema_superseded",
                f"{p['file_kind']} version {p['schema_version']} is not the active version"
                f" ({current or 'none'}); try the file again")
        row = accepted.record(store, db, company_id=p["company_id"], file_kind=p["file_kind"],
                              source_id=p["source_id"], schema_version=p["schema_version"],
                              ticket=item["number"], admitted_by=approver)
        return {"data": {"resolution": "imported"}, "record": {"accepted": row},
                "summary": (f"{p['source_id']} is accepted as {p['file_kind']} version "
                            f"{p['schema_version']} for {p['company_id']}.")}

    return queue.approve(store, ticket, approver, reason, effect=effect, expect="import")


def reject(store: Store, ticket: int, approver: str, reason: str) -> dict:
    """An approver turns down an import or a schema proposal; the ticket goes back to the workers."""
    return queue.reject(store, ticket, approver, reason)

"""Dispositions: what a person decides about an arriving file. There are three.

- import: the file fits an active schema, and an approver admits it. Admission records the file
  as accepted for its company and file kind under that schema version (see accepted.py).
- create_schema: the file needs a schema, or a new version of one. Anyone with access to the
  company's folder drafts it, and an approver confirms it; the confirmation is the create-schema
  gate (schemas.py).
- drop: the file is not needed. An approver drops it, with the reason: a completed disposition, so
  the ticket is finished and its whole history kept (the owner's decision on R6-Q3, build-plan
  section 30). The file stays in the inbox and its ledger; nothing is deleted.

Three cases are kept apart:
- an approver's drop: drop(), final at once, the ticket finished;
- a worker's proposed drop, a decision to discard data: propose("drop"), which waits in the
  approval queue until an approver approves it (approve_drop, which finishes the ticket) or rejects
  it (the ticket goes back to the workers);
- a worker who cannot process a file: not a drop. The worker closes the ticket with the reason
  (Store.close), and the closed ticket's person is told what they may do.

Each decision is a document about the ticket and every step is a journal entry. An admission and an
approved drop are approvals, so they finish the ticket (owner answer S-finish). Writing admitted
rows to extracts/ (Publish) is not built yet.

An import names the trial finding it rests on: a finding about the same ticket that says the file
fits that file kind and schema version. Proposing and admitting both check it, so nothing is
admitted without a verified fit. A drop names the ticket's own file.
"""

from __future__ import annotations

from typing import Optional

from babel.record import queue
from babel.record.store import FINISHED, Store, require, text

from . import accepted, schemas

DISPOSITIONS = ("import", "create_schema", "drop")
#: what a proposal of each kind must name
PAYLOAD = {
    "import": ("company_id", "source_id", "file_kind", "schema_version", "finding"),
    "create_schema": ("company_id", "file_kind", "version"),
    "drop": ("company_id", "source_id"),
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


def own_file(store: Store, db, ticket: int, payload: dict) -> dict:
    """The file a drop names: the ticket's own file, as the ticket's subject names it."""
    subject = store._item(db, ticket)["data"].get("subject") or {}
    require(subject.get("source_id") is not None and subject.get("company_id") == payload.get("company_id")
            and subject.get("source_id") == payload.get("source_id"), "invalid_argument",
            f"#{ticket} is about {subject.get('source_id') or 'no file'} of {subject.get('company_id') or 'no company'}: "
            f"a drop names the ticket's own file, not {payload.get('source_id')} of {payload.get('company_id')}")
    return subject


def drop(store: Store, ticket: int, approver: str, reason: str) -> dict:
    """An approver drops a file that is not needed, with the reason: a completed disposition (the
    owner's decision on R6-Q3, build-plan section 30). The decision is a document about the ticket,
    naming the approver and the reason, and the ticket is finished: its whole history is kept, and it
    is never deleted. The approver takes the claim, so another holder's live lease is respected; a
    ticket waiting on a proposal is decided in the approval queue instead (a proposed drop with
    approve_drop). The file stays in the inbox; nothing is deleted.

    A worker does not drop. A worker who decides the file is not needed proposes the drop (propose
    "drop"), and a worker who cannot process the file closes its ticket with the reason (Store.close).
    """
    reason = text(reason, "reason")
    with store.transaction() as db:
        role = store.acting_role(db, approver, "approver")  # a worker, an agent or a service never drops
        store.approver(db, approver)  # a named person whose name is not agent-like
        item = store._item(db, ticket)
        require(item["kind"] == "task", "not_a_task", f"#{ticket} is a document")
        require(not item["data"].get("proposal"), "proposal_pending",
                f"#{ticket} waits on a proposal: decide it in the approval queue (a proposed drop with approve_drop)")
        store.take(db, ticket, approver, role)  # refuses an ended ticket, and another's live lease
        decision = store.document(
            db, approver, "decision", f"Dropped: #{ticket}",
            f"Dropped by {approver} (approver): {reason}\nThe file stays in the inbox; nothing is deleted.",
            data={"decision": "dropped", "disposition": "drop", "ticket": ticket, "approver": approver,
                  "by": approver, "role": role, "reason": reason, "subject": item["data"].get("subject")},
            about=ticket, role=role)
        data = {**item["data"], "resolution": "dropped", "decisions": item["data"].get("decisions", []) + [decision]}
        return store.update(db, ticket, approver, role=role, action="dropped",
                            note={"reason": reason, "decision": decision}, data=data, status=FINISHED)


def propose(store: Store, ticket: int, actor: str, disposition: str, reason: str, *, payload: dict,
            role: Optional[str] = None) -> dict:
    """Ask an approver for an import, a new schema or a drop; the ticket waits in the approval queue.

    A proposed drop is a worker's decision to discard data, so it is final only when an approver
    approves it (approve_drop), which finishes the ticket; a rejection sends the ticket back to the
    workers (the owner's decision on R6-Q3, build-plan section 30). It names the ticket's own file."""
    require(disposition in PAYLOAD, "invalid_disposition",
            f"an approver decides {sorted(PAYLOAD)}; the dispositions are {DISPOSITIONS}")
    missing = [key for key in PAYLOAD[disposition] if payload.get(key) in (None, "")]
    require(not missing, "invalid_argument", f"a {disposition} proposal must name {', '.join(missing)}")
    if disposition == "import":
        with store.reading() as db:
            fitting_finding(store, db, ticket, payload)
    elif disposition == "drop":
        with store.reading() as db:
            own_file(store, db, ticket, payload)
    return queue.propose(store, ticket, actor, disposition, reason, payload=payload, role=role)


def approve_drop(store: Store, ticket: int, approver: str, reason: str) -> dict:
    """An approver approves a proposed drop: the file is dropped, and the approval, a decision about the
    ticket with the approver's reason, finishes it with its whole history (owner answer S-finish and the
    owner's decision on R6-Q3). The file stays in the inbox; nothing is deleted."""
    def effect(db, item, proposal):
        p = proposal["payload"]
        own_file(store, db, item["number"], p)
        return {"data": {"resolution": "dropped"},
                "record": {"dropped": {"company_id": p["company_id"], "source_id": p["source_id"]}},
                "summary": (f"{p['source_id']} is dropped for {p['company_id']}. The file stays in the inbox; "
                            "nothing is deleted.")}

    return queue.approve(store, ticket, approver, reason, effect=effect, expect="drop")


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

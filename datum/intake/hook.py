"""The intake hook, started by hand: a file path and a company id in, a ticket out.

The folder watcher that will call it is planned, not built (build-plan Q2); until then a person or
a script calls trigger() with the path. Where the file came from is not an input: the same steps
run for a file dragged into a folder or delivered by a collector, and only the schema decides
validity. The hook admits nothing and activates nothing. It acts as the service account "hook",
which holds no role.

trigger():
1. accepts only .xlsx (build-plan Q4) and refuses anything else before writing anything;
2. preserves the file in the company's inbox; a repeat of known bytes is linked to the ticket of
   its first arrival with a comment, and nothing else happens;
3. stages every sheet; a file that cannot be read is unclassified, with the reader's error;
4. for each active schema of the company, cleans the staged sheets for that schema and stores the
   change records (cleaning.py), then tries the cleaned file against it; keeps the schema it fits,
   or the closest (choose());
5. verifies the result before the ticket states it: every sheet is rebuilt from the raw file and
   must give its staged fingerprint, and the rebuilt sheets, cleaned and tried again, must give the
   same result digest. A result that does not reproduce is unclassified;
6. opens one ticket with the routing text and the person's choices, and a finding document with
   the evidence. The hook is the ticket's creator, and the approval queue answers for it and gets
   its notices (RECIPIENT). A file that fits is proposed for import, so it waits for an approver.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from babel.record.store import REVIEW_QUEUE, RecordError, Store
from babel.schema.headers import Versioned

from . import accepted, cleaning, dispositions, inbox, staging, trial
from .inbox import IntakeError
from .schemas import provider as stored_schemas

HOOK = "hook"
#: who answers for an intake ticket and gets its notices: the company's responsible data owner, once real
#: identities name one (P6); until then the approval queue, which named people with the approver role review.
#: The hook stays the ticket's creator (the owner's decision on R6-Q2, build-plan section 30)
RECIPIENT = REVIEW_QUEUE
#: the person's choices on a ticket, by trial outcome (intake.md, routing by the hook's trial)
CHOICES = {
    "no_schema": ["create_schema", "drop"],
    "fits": ["import", "drop"],
    "structural_change": ["create_schema", "drop"],
    "value_problem": ["create_schema", "drop"],
    "schema_defect": ["create_schema", "drop"],
    "wrong_file": ["drop", "create_schema"],
    "unclassified": ["drop", "create_schema"],
}
#: closer outcomes first: used to choose among a company's file kinds when none fits
NEARNESS = {"fits": 0, "value_problem": 1, "schema_defect": 1, "structural_change": 2, "wrong_file": 3}

Schemas = Callable[[str], Sequence[Versioned]]


@dataclass(frozen=True)
class Arrival:
    ticket: int
    source_id: str
    repeated: bool
    outcome: str
    file_kind: Optional[str] = None
    schema_version: Optional[int] = None
    finding: Optional[int] = None


def choose(tried: List[Tuple[Versioned, trial.Result]]) -> Tuple[Optional[Versioned], Optional[trial.Result], str]:
    """The schema a file fits, or the closest one. Two fitting kinds cannot be told apart."""
    fitting = [(v, r) for v, r in tried if r.fits]
    if len(fitting) > 1:
        return None, None, "fits more than one file kind: " + ", ".join(f"{v.file_kind} v{v.version}" for v, _ in fitting)
    if fitting:
        return fitting[0][0], fitting[0][1], ""
    versioned, result = min(tried, key=lambda vr: (NEARNESS[vr[1].outcome], -vr[1].headers_found, vr[0].file_kind))
    return versioned, result, ""


def _accepted_sheets(root, store: Store, company_id: str, versioned: Versioned):
    """The files accepted under this very version, cleaned for it, for the trial's schema-defect
    check. A file accepted under an earlier version keeps that version, and a newer one is not
    checked against it (owner answer P23)."""
    files = []
    for row in accepted.files(store, company_id, versioned.file_kind, schema_version=versioned.version):
        sheets = staging.datasets(root, company_id, row["source_id"]) or staging.stage_all(root, company_id, row["source_id"])
        files.append((row["source_id"], cleaning.clean(sheets, versioned.schema).datasets))
    return files


def _first_rows(sheets) -> List[dict]:
    """Raw evidence for a file with no schema: each sheet's first row with content, as found."""
    evidence = []
    for d in sheets:
        first = next((r for r in d.rows if not r.blank), None)
        evidence.append({"sheet": d.sheet, "rows": len(d.rows), "width": d.width,
                         "first_row": None if first is None else first.source_row,
                         "texts": [] if first is None else [t for t, c in zip(first.texts, first.codes) if c != "e"]})
    return evidence


def _open(store: Store, kept: inbox.Preserved, company_id: str, *, outcome: str, routing: str,
          finding_title: str, finding_body: str, finding_data: dict,
          versioned: Optional[Versioned] = None) -> Tuple[int, int]:
    """One transaction: the ticket, its finding, and the ticket's data pointing at the finding."""
    name = kept.original_name if len(kept.original_name) <= 80 else kept.original_name[:77] + "..."
    subject = {"company_id": company_id, "source_id": kept.source_id, "original_name": kept.original_name,
               "sha256": kept.sha256}
    with store.transaction() as db:
        ticket = store.create_item(
            db, HOOK, "task", "task", f"{name}: {routing}",
            body=(f"{kept.original_name} arrived for {company_id} as {kept.source_id} "
                  f"(sha256 {kept.sha256}).\nTrial: {routing}.\nChoices: {' or '.join(CHOICES[outcome])}."),
            data={"subject": subject}, status="open", origin=f"intake/{company_id}/{kept.source_id}",
            recipient=RECIPIENT)
        finding = store.document(db, HOOK, "finding", finding_title, finding_body,
                                 data={"subject": subject, **finding_data}, about=ticket)
        store.update(db, ticket, HOOK, action="trial_recorded", note={"finding": finding, "outcome": outcome},
                     data={"subject": subject, "choices": CHOICES[outcome],
                           "trial": {"outcome": outcome, "finding": finding,
                                     "file_kind": versioned.file_kind if versioned else None,
                                     "schema_version": versioned.version if versioned else None}})
    return ticket, finding


def trigger(root, company_id: str, path, *, store: Store, schemas: Optional[Schemas] = None) -> Arrival:
    """Run one arriving file through preserve, staging and the trial, and open its ticket.

    `schemas` gives a company's active schema versions; by default, the versions in the store.
    """
    schemas = schemas or stored_schemas(store)
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise IntakeError("unsupported_format", f"{path.name}: only .xlsx files are supported")
    if not _has_user(store, HOOK):
        store.add_user(HOOK, kind="service")
    kept = inbox.preserve(root, company_id, path)
    if kept.repeated:
        ticket = store.find(f"intake/{company_id}/{kept.source_id}")
        if ticket is not None:
            store.comment(ticket, HOOK, f"The same file arrived again as {path.name} (inbox ledger line "
                                        f"{kept.ledger_seq}); it is the file of this ticket. Nothing else was done.")
            trial_data = store.get(ticket)["data"].get("trial", {})
            return Arrival(ticket, kept.source_id, True, trial_data.get("outcome", "unclassified"),
                           trial_data.get("file_kind"), trial_data.get("schema_version"), trial_data.get("finding"))

    def unclassified(why: str, evidence: dict) -> Arrival:
        ticket, finding = _open(
            store, kept, company_id, outcome="unclassified", routing=f"unclassified: {why}",
            finding_title=f"Unclassified: {why}",
            finding_body=f"The file could not be classified: {why}.\nNo cause is suggested. Raw evidence:\n{evidence}",
            finding_data={"outcome": "unclassified", "why": why, "evidence": evidence})
        return Arrival(ticket, kept.source_id, False, "unclassified", finding=finding)

    try:
        sheets = staging.stage_all(root, company_id, kept.source_id)
    except staging.StagingError as error:
        return unclassified("the file could not be staged",
                            {"code": error.code, "message": str(error), "size": kept.size})

    active = list(schemas(company_id))
    if not active:
        ticket, finding = _open(
            store, kept, company_id, outcome="no_schema",
            routing=f"new kind of file for {company_id}: create a schema",
            finding_title=f"No schema yet for files from {company_id}",
            finding_body=(f"{company_id} has no active schema, so the file was not tried. "
                          f"What each sheet holds first, as found:\n{_first_rows(sheets)}"),
            finding_data={"outcome": "no_schema", "sheets": _first_rows(sheets)})
        return Arrival(ticket, kept.source_id, False, "no_schema", finding=finding)

    attempts = []  # (version, its cleaning, the files accepted under it, the trial)
    for v in active:
        cleaned = cleaning.clean(sheets, v.schema)
        cleaning.record(root, company_id, cleaned)
        files = _accepted_sheets(root, store, company_id, v)
        attempts.append((v, cleaned, files, trial.run(cleaned.datasets, v.schema, accepted=files)))
    tried = [(v, r) for v, _, _, r in attempts]
    versioned, result, ambiguity = choose(tried)
    if versioned is None:
        return unclassified(ambiguity, {"tried": [{"file_kind": v.file_kind, "version": v.version,
                                                   "outcome": r.outcome} for v, r in tried]})
    _, cleaned, files, _ = next(a for a in attempts if a[0] is versioned)
    check = trial.verify(root, company_id, kept.source_id, sheets, versioned.schema, result, files)
    if not (check["fingerprints_reproduced"] and check["trial_reproduced"]):
        return unclassified("the trial did not reproduce from the raw file", check)

    label = f"schema {versioned.file_kind} v{versioned.version}"
    routing = (f"fits {label}: ready to import" if result.fits else
               f"wrong file: its headers do not match {label} of {company_id}" if result.outcome == "wrong_file" else
               f"does not fit {label}: {trial.headline(result)}")
    others = [{"file_kind": v.file_kind, "version": v.version, "outcome": r.outcome} for v, r in tried]
    ticket, finding = _open(
        store, kept, company_id, outcome=result.outcome, routing=routing, versioned=versioned,
        finding_title=f"Trial against {label}: {trial.headline(result)}",
        finding_body=(trial.report(result, versioned.schema) + "\n\n" + cleaning.report(cleaned)
                      + "\n\nVerified: every sheet rebuilt from the raw file gives its staged fingerprint, and "
                      "the rebuilt sheets, cleaned and tried again, give the same result "
                      f"(digest {check['result_digest'][:16]})."),
        finding_data={**result.to_dict(), "file_kind": versioned.file_kind, "schema_version": versioned.version,
                      "cleaning": cleaned.summary(), "verification": check, "tried": others})
    if result.fits:
        store.claim(ticket, HOOK)
        dispositions.propose(store, ticket, HOOK, "import", f"The file fits {label} with zero refusals.",
                             payload={"company_id": company_id, "source_id": kept.source_id,
                                      "file_kind": versioned.file_kind, "schema_version": versioned.version,
                                      "finding": finding})
    return Arrival(ticket, kept.source_id, False, result.outcome, versioned.file_kind, versioned.version, finding)


def _has_user(store: Store, name: str) -> bool:
    try:
        store.user(name)
        return True
    except RecordError:
        return False

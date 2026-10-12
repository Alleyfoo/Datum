import sqlite3
from pathlib import Path

import pytest

from babel.intake import accepted, dispositions, inbox
from babel.record import queue
from babel.record.store import CLOSED, RecordError

FIXTURES = Path(__file__).parent / "fixtures"
SUBJECT = {"company_id": "C-100", "source_id": "src_1"}


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _ticket(store, by="ville", outcome="fits"):
    """A ticket with the trial finding the hook would write about it, claimed by `by`."""
    task = store.add_task("hook", f"stock_export.xlsx: {outcome} schema stock_export v1", data={"subject": SUBJECT})
    store.add_document("hook", "finding", f"Trial against stock_export v1: {outcome}", "evidence",
                       data={"subject": SUBJECT, "outcome": outcome, "file_kind": "stock_export",
                             "schema_version": 1}, about=task)
    store.claim(task, by)
    return task


def _import(store, task):
    [finding] = store.documents_about(task, "finding")
    return {**SUBJECT, "file_kind": "stock_export", "schema_version": 1, "finding": finding["number"]}


def test_a_worker_drops_a_file_with_a_reason_and_nothing_is_deleted(store, data_root):
    kept = inbox.preserve(data_root, "C-100", FIXTURES / "stock_export_2026-08-21.xlsx")
    task = _ticket(store)
    item = dispositions.drop(store, task, "ville", "Duplicate of last week's export")
    assert (item["status"], item["data"]["resolution"], item["claimed_by"]) == (CLOSED, "dropped", None)
    [decision] = store.documents_about(task, "decision")
    assert decision["data"]["decision"] == "dropped"
    assert (decision["data"]["by"], decision["data"]["role"]) == ("ville", "worker")
    assert decision["data"]["reason"] == "Duplicate of last week's export"
    dropped = [e for e in store.journal(task) if e["action"] == "dropped"]
    assert dropped[0]["details"]["reason"] == "Duplicate of last week's export"
    assert kept.path.exists() and inbox.verify(data_root, "C-100", kept.source_id)["matches"]


def test_dropping_needs_the_claim_a_reason_and_a_person(store):
    task = store.add_task("hook", "A file arrived")
    assert _code(dispositions.drop, store, task, "ville", "not needed") == "claim_required"
    store.claim(task, "ville")
    assert _code(dispositions.drop, store, task, "ville", "") == "invalid_argument"
    other = store.add_task("hook", "Another file")
    store.claim(other, "hook")
    assert _code(dispositions.drop, store, other, "hook", "not needed") == "role_missing"


def test_an_approver_may_drop_too(store):
    task = _ticket(store, by="anna")
    assert dispositions.drop(store, task, "anna", "Out of scope")["data"]["resolution"] == "dropped"


def test_a_worker_cannot_admit_an_approver_can(store):
    task = _ticket(store)
    dispositions.propose(store, task, "ville", "import", "Fits with zero refusals", payload=_import(store, task))
    assert _code(dispositions.admit, store, task, "ville", "fine") == "role_missing"
    assert accepted.files(store, "C-100", "stock_export") == []

    item = dispositions.admit(store, task, "anna", "Trial checked: 19 rows, no refusals")
    assert (item["status"], item["data"]["resolution"]) == (CLOSED, "imported")
    [row] = accepted.files(store, "C-100", "stock_export")
    assert (row["source_id"], row["schema_version"], row["ticket"], row["admitted_by"]) == ("src_1", 1, task, "anna")
    [decision] = store.documents_about(task, "decision")
    assert decision["data"]["accepted"]["source_id"] == "src_1"
    assert "accepted as stock_export version 1 for C-100" in decision["body"]


def test_a_file_is_accepted_once_and_stays_accepted(store):
    first = _ticket(store)
    dispositions.propose(store, first, "ville", "import", "fits", payload=_import(store, first))
    dispositions.admit(store, first, "anna", "fits")
    second = _ticket(store)
    dispositions.propose(store, second, "ville", "import", "fits", payload=_import(store, second))
    assert _code(dispositions.admit, store, second, "anna", "fits") == "already_accepted"
    assert store.get(second)["status"] == "needs_input"
    db = sqlite3.connect(store.path)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("DELETE FROM accepted_files")
    finally:
        db.close()


def test_a_schema_proposal_waits_for_an_approver_and_is_not_an_import(store):
    task = _ticket(store)
    dispositions.propose(store, task, "ville", "create_schema", "New kind of file",
                         payload={"company_id": "C-100", "file_kind": "stock_export", "version": 1})
    assert [q["action"] for q in queue.pending(store)] == ["create_schema"]
    assert _code(dispositions.admit, store, task, "anna", "fits") == "wrong_action"


def test_there_are_three_dispositions_and_proposals_name_their_file(store):
    task = _ticket(store)
    assert dispositions.DISPOSITIONS == ("import", "create_schema", "drop")
    assert _code(dispositions.propose, store, task, "ville", "export", "why not", payload={}) == "invalid_disposition"
    assert _code(dispositions.propose, store, task, "ville", "drop", "duplicate", payload={}) == "invalid_disposition"
    assert _code(dispositions.propose, store, task, "ville", "import", "fits",
                 payload={"company_id": "C-100"}) == "invalid_argument"


def test_an_import_needs_a_trial_finding_that_says_the_file_fits(store):
    task = _ticket(store, outcome="structural_change")
    assert _code(dispositions.propose, store, task, "ville", "import", "looks fine",
                 payload=_import(store, task)) == "no_fitting_trial"
    other = _ticket(store)
    wrong_version = {**_import(store, other), "schema_version": 2}
    assert _code(dispositions.propose, store, other, "ville", "import", "fits",
                 payload=wrong_version) == "no_fitting_trial"
    borrowed = {**_import(store, other), "finding": store.documents_about(task, "finding")[0]["number"]}
    assert _code(dispositions.propose, store, other, "ville", "import", "fits",
                 payload=borrowed) == "no_fitting_trial"


def test_a_rejected_import_goes_back_to_the_workers(store):
    task = _ticket(store)
    dispositions.propose(store, task, "ville", "import", "fits", payload=_import(store, task))
    item = dispositions.reject(store, task, "anna", "Wait for the corrected export")
    assert item["status"] == "open" and accepted.files(store, "C-100", "stock_export") == []


def test_every_step_is_in_the_journal(store):
    task = _ticket(store)
    dispositions.propose(store, task, "ville", "import", "fits", payload=_import(store, task))
    dispositions.admit(store, task, "anna", "fits")
    steps = [(e["actor"], e["role"], e["action"]) for e in store.journal(task)]
    assert steps == [
        ("hook", "system", "created"),
        ("ville", "worker", "claimed"),
        ("ville", "worker", "proposed"),
        ("ville", "worker", "released"),
        ("anna", "approver", "claimed"),
        ("anna", "approver", "approved"),
    ]

import sqlite3
from pathlib import Path

import pytest

from datum.intake import accepted, dispositions, inbox
from datum.record import queue
from datum.record.store import CLOSED, ENDS, FINISHED, RecordError

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


def test_an_approver_drops_a_file_with_a_reason_and_nothing_is_deleted(store, data_root):
    kept = inbox.preserve(data_root, "C-100", FIXTURES / "stock_export_2026-08-21.xlsx")
    task = _ticket(store, by="anna")
    item = dispositions.drop(store, task, "anna", "Duplicate of last week's export")
    assert (item["status"] in ENDS, item["data"]["resolution"], item["claimed_by"]) == (True, "dropped", None)
    [decision] = store.documents_about(task, "decision")
    assert decision["data"]["decision"] == "dropped"
    assert (decision["data"]["by"], decision["data"]["role"]) == ("anna", "approver")
    assert decision["data"]["reason"] == "Duplicate of last week's export"
    dropped = [e for e in store.journal(task) if e["action"] == "dropped"]
    assert dropped[0]["details"]["reason"] == "Duplicate of last week's export"
    assert kept.path.exists() and inbox.verify(data_root, "C-100", kept.source_id)["matches"]


def test_dropping_needs_a_reason_and_a_person(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "anna")
    assert _code(dispositions.drop, store, task, "anna", "") == "invalid_argument"
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
    assert item["status"] in ENDS and item["data"]["resolution"] == "imported"
    [row] = accepted.files(store, "C-100", "stock_export")
    assert (row["source_id"], row["schema_version"], row["ticket"], row["admitted_by"]) == ("src_1", 1, task, "anna")
    [decision] = store.documents_about(task, "decision")
    assert decision["data"]["accepted"]["source_id"] == "src_1"
    assert "accepted as stock_export version 1 for C-100" in decision["body"]


def test_an_admission_finishes_the_ticket_and_a_worker_who_cannot_process_the_file_closes_it(store):
    # S-finish and S-closed (build-plan sections 27 and 29): an approver's admission finishes; a worker
    # closes work it cannot process, with the reason (the owner's decision on R6-Q3, section 30)
    admitted, unprocessable = _ticket(store), _ticket(store)
    dispositions.propose(store, admitted, "ville", "import", "Fits", payload=_import(store, admitted))
    assert dispositions.admit(store, admitted, "anna", "Trial checked")["status"] == FINISHED
    assert store.close(unprocessable, "ville", "The workbook's sheets cannot be read")["status"] == CLOSED


def test_a_worker_closes_a_file_it_cannot_process_and_a_notice_follows(store):
    # S-closed (build-plan section 27): a close is followed by its notice; a worker's inability to process
    # a file is a close, not a drop: no drop decision, no resolution
    task = _ticket(store)
    store.close(task, "ville", "The workbook's sheets cannot be read")
    closed, told = store.journal(task)[-2:]
    assert (closed["action"], closed["details"]["reason"], told["action"], told["actor"]) == (
        "closed", "The workbook's sheets cannot be read", "notice", "system")
    assert store.documents_about(task, "decision") == [] and "resolution" not in store.get(task)["data"]


def test_an_approvers_drop_finishes_the_ticket_and_keeps_its_history(store, data_root, clock):
    # the owner's decision on R6-Q3 (build-plan section 30): an approver's deliberate drop of a file that
    # is not needed is a completed disposition: finished, with the decision and its reason, never deleted
    kept = inbox.preserve(data_root, "C-100", FIXTURES / "stock_export_2026-08-21.xlsx")
    task = _ticket(store)
    store.release(task, "ville")
    item = dispositions.drop(store, task, "anna", "Duplicate of last week's export")
    assert (item["status"], item["claimed_by"], item["data"]["resolution"]) == (FINISHED, None, "dropped")
    [decision] = store.documents_about(task, "decision")
    assert (decision["data"]["decision"], decision["data"]["approver"], decision["data"]["reason"]) == (
        "dropped", "anna", "Duplicate of last week's export")
    assert item["data"]["decisions"] == [decision["number"]]
    claimed, dropped = store.journal(task)[-2:]
    assert (claimed["actor"], claimed["action"], dropped["actor"], dropped["role"], dropped["action"]) == (
        "anna", "claimed", "anna", "approver", "dropped")
    assert dropped["details"]["status"] == {"before": "open", "after": FINISHED}
    assert "notice" not in [e["action"] for e in store.journal(task)]  # finished: nothing to tell
    history = store.journal(task)
    clock.advance(days=3650)
    assert store.sweep(clock()) == []
    assert (store.get(task)["status"], store.journal(task)) == (FINISHED, history)
    assert kept.path.exists() and inbox.verify(data_root, "C-100", kept.source_id)["matches"]


def test_a_worker_does_not_drop_a_file_and_an_approvers_drop_respects_anothers_lease(store, clock):
    task = _ticket(store)  # ville, a worker, holds it
    assert _code(dispositions.drop, store, task, "ville", "Not needed") == "role_missing"
    store.add_user("drafting-assistant", ["worker"], kind="agent")
    assert _code(dispositions.drop, store, task, "drafting-assistant", "Not needed") == "role_missing"
    assert _code(dispositions.drop, store, task, "anna", "Not needed") == "claim_conflict"  # ville's live lease
    assert (store.get(task)["status"], store.documents_about(task, "decision")) == ("open", [])
    clock.advance(seconds=store.lease.total_seconds() + 60)
    assert dispositions.drop(store, task, "anna", "Not needed")["status"] == FINISHED


def test_a_workers_proposed_drop_waits_for_an_approver_whose_approval_finishes_the_ticket(store):
    # the owner's decision on R6-Q3: a worker's decision to discard data goes to an approver before it is final
    task = _ticket(store)
    dispositions.propose(store, task, "ville", "drop", "Duplicate of last week's export", payload=SUBJECT)
    item = store.get(task)
    assert (item["status"], item["claimed_by"], "resolution" in item["data"]) == ("needs_input", None, False)
    [waiting] = queue.pending(store)
    assert (waiting["number"], waiting["action"], waiting["proposed_by"], waiting["payload"]) == (
        task, "drop", "ville", SUBJECT)
    assert _code(dispositions.drop, store, task, "anna", "Not needed") == "proposal_pending"  # decided in the queue
    assert _code(dispositions.approve_drop, store, task, "ville", "Fine") == "role_missing"
    item = dispositions.approve_drop(store, task, "anna", "Yes: the same rows as last week")
    assert (item["status"], item["data"]["resolution"]) == (FINISHED, "dropped")
    [decision] = store.documents_about(task, "decision")
    assert (decision["data"]["decision"], decision["data"]["action"], decision["data"]["approver"]) == (
        "approved", "drop", "anna")
    assert decision["data"]["dropped"] == SUBJECT and "The file stays in the inbox" in decision["body"]


def test_a_proposed_drop_names_the_tickets_own_file_and_a_rejection_sends_it_back(store):
    task = _ticket(store)
    assert _code(dispositions.propose, store, task, "ville", "drop", "Not needed", payload={}) == "invalid_argument"
    assert _code(dispositions.propose, store, task, "ville", "drop", "Not needed",
                 payload={**SUBJECT, "source_id": "src_2"}) == "invalid_argument"
    plain = store.add_task("hook", "Not about a file")
    store.claim(plain, "ville")
    assert _code(dispositions.propose, store, plain, "ville", "drop", "Not needed", payload=SUBJECT) == "invalid_argument"
    dispositions.propose(store, task, "ville", "drop", "Not needed", payload=SUBJECT)
    item = dispositions.reject(store, task, "anna", "We need this export: it is the corrected one")
    assert (item["status"], item["claimed_by"], "resolution" in item["data"]) == ("open", None, False)
    assert [t["number"] for t in store.ready()] == [task]


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

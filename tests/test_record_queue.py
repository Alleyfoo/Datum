import pytest

from babel.record import queue
from babel.record.store import RecordError


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _proposed(store, action="import", by="ville"):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, by)
    queue.propose(store, task, by, action, "Fits the schema; ready to import",
                  payload={"source_id": "src_1"})
    return task


def test_a_proposal_parks_the_ticket_in_the_queue_and_hands_the_claim_back(store):
    task = _proposed(store)
    item = store.get(task)
    assert (item["status"], item["claimed_by"]) == ("needs_input", None)
    assert queue.pending(store) == [{
        "number": task, "title": "A file arrived", "action": "import",
        "reason": "Fits the schema; ready to import", "proposed_by": "ville", "proposed_role": "worker",
        "payload": {"source_id": "src_1"}, "assignee": None, "findings": [],
    }]
    proposed = [e for e in store.journal(task) if e["action"] == "proposed"][0]
    assert proposed["details"]["reason"] == "Fits the schema; ready to import"
    assert store.ready() == []


def test_a_proposal_needs_the_claim_and_only_one_waits_at_a_time(store):
    task = store.add_task("hook", "A file arrived")
    assert _code(queue.propose, store, task, "ville", "import", "fits") == "claim_required"
    task = _proposed(store)
    store.claim(task, "ville")
    assert _code(queue.propose, store, task, "ville", "drop", "duplicate") == "proposal_pending"


def test_a_worker_cannot_approve_and_the_attempt_is_recorded(store):
    task = _proposed(store)
    assert _code(queue.approve, store, task, "ville", "looks fine") == "role_missing"
    refused = store.journal(task)[-1]
    assert (refused["actor"], refused["action"], refused["details"]["code"]) == ("ville", "approval_refused", "role_missing")
    assert store.get(task)["status"] == "needs_input"


def test_an_agent_cannot_approve(store):
    store.add_user("drafting-assistant", ["worker"], kind="agent")
    task = _proposed(store)
    assert _code(queue.approve, store, task, "drafting-assistant", "fits") == "agent_approver"


def test_an_approval_is_a_named_decision_document_about_the_ticket(store):
    task = _proposed(store)
    done = queue.approve(store, task, "anna", "Checked the trial; admit it")
    assert (done["status"], done["claimed_by"]) == ("done", None)
    assert "proposal" not in done["data"]
    [decision] = store.documents_about(task, "decision")
    assert decision["data"]["decision"] == "approved"
    assert (decision["data"]["approver"], decision["data"]["reason"]) == ("anna", "Checked the trial; admit it")
    assert decision["body"].startswith("Approved by anna (approver): Checked the trial; admit it")
    assert done["data"]["decisions"] == [decision["number"]]
    approved = [e for e in store.journal(task) if e["action"] == "approved"][0]
    assert (approved["actor"], approved["role"], approved["details"]["decision"]) == ("anna", "approver", decision["number"])
    assert queue.pending(store) == []


def test_the_drafter_may_also_approve_when_holding_both_roles(store):
    task = _proposed(store, by="pia")
    assert queue.approve(store, task, "pia", "I drafted it and confirm it")["status"] == "done"


def test_an_effect_can_lead_to_a_next_proposal(store):
    task = _proposed(store, action="create_schema")
    seen = []

    def effect(db, ticket, proposal):
        seen.append(proposal["action"])
        return {"proposal": {"action": "import", "reason": "the file now fits"},
                "title": "Fits schema v2: ready to import", "record": {"version": 2},
                "summary": "gate: all checks passed"}

    item = queue.approve(store, task, "anna", "the rules are right", effect=effect)
    assert seen == ["create_schema"]
    assert (item["status"], item["title"], item["claimed_by"]) == ("needs_input", "Fits schema v2: ready to import", None)
    assert item["data"]["proposal"]["action"] == "import" and item["data"]["proposal"]["by"] == "anna"
    [decision] = store.documents_about(task, "decision")
    assert decision["data"]["version"] == 2 and decision["body"].endswith("gate: all checks passed")
    assert [q["action"] for q in queue.pending(store)] == ["import"]


def test_a_refusing_effect_changes_nothing_but_the_journal(store):
    task = _proposed(store, action="create_schema")

    def effect(db, ticket, proposal):
        raise RecordError("regression", "an accepted file no longer passes")

    before = store.get(task)
    assert _code(queue.approve, store, task, "anna", "confirm", effect=effect) == "regression"
    after = store.get(task)
    assert (after["status"], after["version"], after["claimed_by"]) == (before["status"], before["version"], None)
    assert store.documents_about(task) == []
    assert store.journal(task)[-1]["action"] == "approval_refused"
    assert store.journal(task)[-1]["details"]["code"] == "regression"


def test_a_rejection_sends_the_ticket_back_to_the_workers(store):
    task = _proposed(store)
    item = queue.reject(store, task, "anna", "The trial is from last week's file")
    assert (item["status"], item["claimed_by"]) == ("open", None)
    assert "proposal" not in item["data"]
    [decision] = store.documents_about(task, "decision")
    assert decision["data"]["decision"] == "rejected"
    assert [t["number"] for t in store.ready()] == [task]


def test_an_approver_waits_for_another_holders_lease(store, clock):
    task = _proposed(store)
    store.claim(task, "pia")
    assert _code(queue.approve, store, task, "anna", "fits") == "claim_conflict"
    clock.advance(minutes=31)
    assert queue.approve(store, task, "anna", "fits")["status"] == "done"


def test_a_decision_needs_a_reason_and_something_to_decide(store):
    task = _proposed(store)
    assert _code(queue.approve, store, task, "anna", "  ") == "invalid_argument"
    other = store.add_task("hook", "Nothing proposed here")
    assert _code(queue.approve, store, other, "anna", "fits") == "nothing_to_decide"
    assert _code(queue.approve, store, task, "anna", "fits", expect="create_schema") == "wrong_action"

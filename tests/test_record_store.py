import sqlite3

import pytest

from babel.record.store import RecordError, agent_like

# the clock and store fixtures are in conftest.py


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def test_tasks_and_documents_share_one_number_sequence(store):
    first = store.add_task("hook", "A file arrived")
    finding = store.add_document("hook", "finding", "The file fits", "19 rows, 0 refusals", about=first)
    second = store.add_task("hook", "Another file arrived")
    assert (first, finding, second) == (1, 2, 3)
    assert [store.get(n)["kind"] for n in (first, finding, second)] == ["task", "document", "task"]
    assert [d["number"] for d in store.documents_about(first)] == [finding]


def test_numbers_are_never_reused_and_the_journal_is_append_only(store):
    store.add_task("hook", "A file arrived")
    db = sqlite3.connect(store.path)
    try:
        for statement in ("DELETE FROM items", "UPDATE journal SET actor='anna'", "DELETE FROM journal"):
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(statement)
    finally:
        db.close()
    assert store.add_task("hook", "Next") == 2


def test_every_state_change_is_an_attributed_journal_entry(store):
    task = store.add_task("hook", "A file arrived")
    blocker = store.add_task("hook", "Something first")
    store.claim(task, "ville")
    store.set_status(task, "ville", "in_progress")
    store.comment(task, "ville", "Looked at the header row.")
    finding = store.add_document("ville", "finding", "Header differs", "c004 renamed", about=task)
    store.link("ville", blocker, "blocks", task)
    store.release(task, "ville")
    entries = [(e["item"], e["actor"], e["role"], e["action"]) for e in store.journal()
               if e["action"] != "user_added"]
    assert entries == [
        (task, "hook", "system", "created"),
        (blocker, "hook", "system", "created"),
        (task, "ville", "worker", "claimed"),
        (task, "ville", "worker", "status_changed"),
        (task, "ville", "worker", "comment"),
        (finding, "ville", "worker", "created"),
        (finding, "ville", "worker", "linked"),
        (blocker, "ville", "worker", "linked"),
        (task, "ville", "worker", "released"),
    ]
    assert store.journal(task)[2]["details"] == {"status": {"before": "open", "after": "in_progress"}}


def _past_the_lease(store, clock):
    """Move the clock a minute past the store's lease, with no write in between."""
    clock.advance(seconds=store.lease.total_seconds() + 60)


def test_a_claim_keeps_others_out_until_its_lease_runs_out(store, clock):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    claimed_at = clock()
    assert _code(store.claim, task, "pia") == "claim_conflict"
    _past_the_lease(store, clock)  # ville stopped working: nothing renewed the lease
    assert not store.get(task)["lease_active"]
    store.claim(task, "pia")
    assert store.get(task)["claimed_by"] == "pia"
    expired_at = (claimed_at + store.lease).isoformat(timespec="seconds")
    assert store.journal(task)[-1]["details"] == {"previous": "ville", "expired_at": expired_at}


def test_writes_by_the_holder_renew_the_lease(store, clock):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    two_thirds = store.lease.total_seconds() * 2 / 3
    clock.advance(seconds=two_thirds)
    store.comment(task, "ville", "Still on it.")
    clock.advance(seconds=two_thirds)  # past the lease counted from the claim, inside it from the comment
    assert store.get(task)["lease_active"]
    assert _code(store.claim, task, "pia") == "claim_conflict"


def test_a_holder_whose_lease_ran_out_must_claim_again(store, clock):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    _past_the_lease(store, clock)
    assert _code(store.set_status, task, "ville", "in_progress") == "claim_expired"
    store.claim(task, "ville")
    assert store.set_status(task, "ville", "in_progress")["status"] == "in_progress"


def test_a_change_needs_the_claim(store):
    task = store.add_task("hook", "A file arrived")
    assert _code(store.set_status, task, "ville", "in_progress") == "claim_required"
    store.claim(task, "ville")
    assert _code(store.set_status, task, "pia", "done") == "claim_required"
    assert _code(store.release, task, "pia") == "release_forbidden"


def test_finishing_hands_the_claim_back(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    done = store.set_status(task, "ville", "done")
    assert (done["status"], done["claimed_by"], done["lease_until"]) == ("done", None, None)
    assert store.journal(task)[-1]["details"]["released"] == "ville"
    assert _code(store.claim, task, "pia") == "item_done"


def test_blocked_tasks_are_not_ready_until_the_blocker_is_done(store):
    first = store.add_task("hook", "Create the schema")
    second = store.add_task("hook", "Import the file")
    store.link("ville", first, "blocks", second)
    assert [t["number"] for t in store.ready()] == [first]
    store.claim(first, "ville")
    store.set_status(first, "ville", "done")
    assert [t["number"] for t in store.ready()] == [second]


def test_a_task_held_by_someone_else_is_not_ready_for_others(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    assert store.ready("pia") == []
    assert [t["number"] for t in store.ready("ville")] == [task]


def test_parked_tasks_are_not_ready(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    store.set_status(task, "ville", "needs_input")
    store.release(task, "ville")
    assert store.ready() == []


def test_roles_live_on_the_user_record(store):
    assert store.user("pia")["roles"] == ("approver", "worker")
    assert _code(store.add_user, "helper", ["approver"], kind="agent") == "agent_approver"
    assert _code(store.add_user, "claude-code", ["approver"]) == "agent_approver"
    assert _code(store.add_user, "AgentSmith", ["approver"]) == "agent_approver"
    assert _code(store.add_user, "collector", ["worker"], kind="service") == "invalid_role"
    assert _code(store.add_user, "anna", ["worker"]) == "user_exists"
    store.add_user("drafter", ["worker"], kind="agent")  # an agent may work tickets, never approve
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    assert _code(store.set_status, task, "ville", "in_progress", role="approver") == "role_missing"


@pytest.mark.parametrize("name, expected", [
    ("Anna Virtanen", False), ("Abbott", False), ("Päivi", False),
    ("assistant", True), ("Claude", True), ("gpt-5", True), ("the hook", True), ("MCP server", True),
])
def test_agent_like_names(name, expected):
    assert agent_like(name) is expected


def test_the_same_origin_opens_one_task(store):
    first = store.add_task("hook", "A file arrived", origin="intake/C-100/src_1")
    again = store.add_task("hook", "A file arrived", origin="intake/C-100/src_1")
    assert first == again
    assert [e["action"] for e in store.journal(first)] == ["created"]


def test_a_stale_version_is_refused(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    version = store.get(task)["version"]
    store.set_status(task, "ville", "in_progress", expected_version=version)
    assert _code(store.set_status, task, "ville", "needs_input", expected_version=version) == "version_conflict"


def test_anyone_may_comment_even_on_a_finished_task(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    store.set_status(task, "ville", "done")
    store.comment(task, "anna", "Checked after the fact.")
    assert store.journal(task)[-1]["details"] == {"body": "Checked after the fact."}
    assert store.journal(task)[-1]["role"] == "approver"

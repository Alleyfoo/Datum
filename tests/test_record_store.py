import json
import sqlite3

import pytest

from babel.record.store import CLOSED, TASK_STATUSES, RecordError, Store, agent_like

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


@pytest.mark.parametrize("last_write", ["claim", "comment"])
def test_a_lease_runs_for_one_day_from_the_holders_last_write(store, clock, last_write):
    # P22, the owner's answer (build-plan section 20): one day
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    if last_write == "comment":
        clock.advance(hours=10)
        store.comment(task, "ville", "Half way through the rows.")  # the day starts again here
    clock.advance(hours=23)  # 23 hours without a write: still held
    assert store.get(task)["lease_active"]
    assert _code(store.claim, task, "pia") == "claim_conflict"
    clock.advance(hours=2)  # 25 hours without a write: run out
    assert not store.get(task)["lease_active"]
    assert store.claim(task, "pia")["claimed_by"] == "pia"


def test_a_change_needs_the_claim(store):
    task = store.add_task("hook", "A file arrived")
    assert _code(store.set_status, task, "ville", "in_progress") == "claim_required"
    store.claim(task, "ville")
    assert _code(store.set_status, task, "pia", CLOSED) == "claim_required"
    assert _code(store.release, task, "pia") == "release_forbidden"


def test_finishing_hands_the_claim_back(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    closed = store.set_status(task, "ville", CLOSED)
    assert (closed["status"], closed["claimed_by"], closed["lease_until"]) == (CLOSED, None, None)
    assert store.journal(task)[-1]["details"]["released"] == "ville"
    assert _code(store.claim, task, "pia") == f"item_{CLOSED}"


def test_blocked_tasks_are_not_ready_until_the_blocker_is_closed(store):
    first = store.add_task("hook", "Create the schema")
    second = store.add_task("hook", "Import the file")
    store.link("ville", first, "blocks", second)
    assert [t["number"] for t in store.ready()] == [first]
    store.claim(first, "ville")
    store.set_status(first, "ville", CLOSED)
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


def test_opening_an_open_ticket_hands_it_to_the_opener(store):
    # T-open (build-plan section 10): opening sets in_progress, and the log says who and when
    task = store.add_task("hook", "A customer called")
    opened = store.open_ticket(task, "ville")
    assert (opened["status"], opened["claimed_by"], opened["lease_active"]) == ("in_progress", "ville", True)
    entries = [(e["actor"], e["role"], e["action"], e["details"]) for e in store.journal(task)]
    assert entries[1:] == [("ville", "worker", "claimed", {}),
                           ("ville", "worker", "opened", {"status": {"before": "open", "after": "in_progress"}})]
    assert store.journal(task)[-1]["at"] == store.now()


def test_opening_a_ticket_already_in_progress_changes_nothing(store):
    task = store.add_task("hook", "A customer called")
    store.open_ticket(task, "ville")
    before = (store.get(task), len(store.journal(task)))
    for opener in ("ville", "pia"):
        assert store.open_ticket(task, opener) == before[0]
    assert (store.get(task), len(store.journal(task))) == before


def test_a_ticket_waiting_on_a_decision_or_closed_is_not_opened(store):
    parked = store.add_task("hook", "Waits on an approver")
    store.claim(parked, "ville")
    store.set_status(parked, "ville", "needs_input")
    store.release(parked, "ville")
    closed = store.add_task("hook", "Finished")
    store.claim(closed, "ville")
    store.set_status(closed, "ville", CLOSED)
    assert _code(store.open_ticket, parked, "pia") == "not_open"
    assert _code(store.open_ticket, closed, "pia") == "not_open"
    assert store.get(parked)["status"] == "needs_input"


def test_released_without_a_decision_a_ticket_goes_back_to_open(store):
    # T-release (build-plan section 10): the history stays, and the next handler can open it
    task = store.add_task("hook", "A customer called")
    store.open_ticket(task, "ville")
    released = store.release(task, "ville")
    assert (released["status"], released["claimed_by"], released["lease_until"]) == ("open", None, None)
    assert store.journal(task)[-1]["details"] == {"status": {"before": "in_progress", "after": "open"}}
    assert [t["number"] for t in store.ready("pia")] == [task]
    assert store.open_ticket(task, "pia")["claimed_by"] == "pia"
    assert [e["action"] for e in store.journal(task)] == [
        "created", "claimed", "opened", "released", "claimed", "opened"]


def test_a_release_keeps_why_in_its_journal_entry(store):
    # P26 (build-plan section 25): the journal records who released a ticket, when, and why
    task = store.add_task("hook", "A customer called")
    store.open_ticket(task, "ville")
    released = store.release(task, "ville", reason="The customer will call back")
    entry = store.journal(task)[-1]
    assert (entry["actor"], entry["role"], entry["action"], entry["at"]) == ("ville", "worker", "released", store.now())
    assert entry["details"] == {"status": {"before": "in_progress", "after": "open"},
                                "reason": "The customer will call back"}
    assert (released["status"], released["claimed_by"]) == ("open", None)
    store.open_ticket(task, "pia")
    assert _code(store.release, task, "pia", reason="  ") == "invalid_argument"
    assert (store.get(task)["claimed_by"], store.journal(task)[-1]["action"]) == ("pia", "opened")


def test_resuming_an_open_ticket_hands_it_to_whoever_resumes_it(store):
    # P26 (build-plan section 25): resume takes up a ticket released without a decision
    task = store.add_task("hook", "A customer called")
    store.open_ticket(task, "ville")
    store.release(task, "ville", reason="The customer will call back")
    resumed = store.resume(task, "pia")
    assert (resumed["status"], resumed["claimed_by"], resumed["lease_active"]) == ("in_progress", "pia", True)
    assert [(e["actor"], e["role"], e["action"], e["details"]) for e in store.journal(task)[-2:]] == [
        ("pia", "worker", "claimed", {}),
        ("pia", "worker", "resumed", {"status": {"before": "open", "after": "in_progress"}})]
    assert store.journal(task)[-1]["at"] == store.now()


def test_a_ticket_whose_holders_lease_ran_out_is_resumed_by_the_next_agent(store, clock):
    # Q-stale leaves it in_progress when the lease runs out; resume is how another agent takes it up
    task = store.add_task("hook", "A customer called")
    store.open_ticket(task, "ville")
    assert _code(store.resume, task, "pia") == "claim_conflict"  # ville's lease is live
    ran_out = store.get(task)["lease_until"]
    clock.advance(seconds=store.lease.total_seconds() + 60)
    resumed = store.resume(task, "pia")
    assert (resumed["status"], resumed["claimed_by"], resumed["lease_active"]) == ("in_progress", "pia", True)
    claimed, entry = store.journal(task)[-2:]
    assert claimed["details"] == {"previous": "ville", "expired_at": ran_out}
    assert (entry["actor"], entry["action"], entry["details"]) == (
        "pia", "resumed", {"previous": "ville", "lease_ran_out": ran_out})


def test_resuming_a_held_ticket_changes_nothing_and_a_waiting_or_closed_one_is_not_resumed(store):
    task = store.add_task("hook", "A customer called")
    store.open_ticket(task, "ville")
    before = (store.get(task), len(store.journal(task)))
    assert store.resume(task, "ville") == before[0]
    assert len(store.journal(task)) == before[1]
    parked = store.add_task("hook", "Waits on an approver")
    store.claim(parked, "ville")
    store.set_status(parked, "ville", "needs_input")
    store.release(parked, "ville")
    assert _code(store.resume, parked, "pia") == "not_open"
    store.set_status(task, "ville", CLOSED)
    with pytest.raises(RecordError, match=f"#{task} is closed: its work has stopped, so it is not resumed") as refused:
        store.resume(task, "pia")
    assert refused.value.code == "item_closed"
    assert _code(store.resume, store.add_document("hook", "finding", "A finding", "text"), "pia") == "not_a_task"
    assert [store.get(n)["status"] for n in (task, parked)] == ["closed", "needs_input"]


def test_a_lease_that_runs_out_leaves_the_ticket_in_progress(store, clock):
    # Q-stale (build-plan section 20): only a release returns it to open
    task = store.add_task("hook", "A customer called")
    store.open_ticket(task, "ville")
    clock.advance(seconds=store.lease.total_seconds() + 60)
    item = store.get(task)
    assert (item["status"], item["claimed_by"], item["lease_active"]) == ("in_progress", "ville", False)


def test_done_is_called_closed_among_a_tasks_statuses(store):
    # P25 (build-plan section 25): done is called closed. Which statuses follow it is the owner's list, its own test
    assert CLOSED == "closed" and "done" not in TASK_STATUSES
    assert TASK_STATUSES[:4] == ("open", "in_progress", "needs_input", "closed")
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    assert _code(store.set_status, task, "ville", "done") == "invalid_status"
    closed = store.set_status(task, "ville", "closed")
    assert store.journal(task)[-1]["details"]["status"] == {"before": "open", "after": "closed"}
    with pytest.raises(RecordError, match=f"#{task} is closed") as refused:
        store.claim(task, "pia")
    assert (closed["status"], refused.value.code) == ("closed", "item_closed")


def _written_before_the_rename(store, number):
    """Leave #number as the code before P25 did on closing it: status done, its journal entry
    saying so, and the store without a version."""
    db = sqlite3.connect(store.path)
    try:
        db.execute("UPDATE items SET status='done', claimed_by=NULL, lease_until=NULL WHERE number=?", (number,))
        db.execute("INSERT INTO journal (item, actor, role, action, details, at) VALUES (?,?,?,?,?,?)",
                   (number, "ville", "worker", "status_changed",
                    json.dumps({"status": {"before": "open", "after": "done"}, "released": "ville"}), store.now()))
        db.execute("PRAGMA user_version=0")
        db.commit()
    finally:
        db.close()


def test_a_store_written_with_done_opens_with_closed(store, clock):
    # P25: one migration step, run once when an older store opens; the journal keeps its history
    finished, waiting = store.add_task("hook", "Finished"), store.add_task("hook", "Still open")
    _written_before_the_rename(store, finished)
    before = store.get(finished)
    clock.advance(hours=1)
    reopened = Store(store.path, clock=clock)
    item = reopened.get(finished)
    assert (item["status"], item["version"], item["updated_at"]) == ("closed", before["version"] + 1, reopened.now())
    *history, migrated = reopened.journal(finished)
    assert history[-1]["details"]["status"]["after"] == "done"  # what was written then stays written
    assert (migrated["actor"], migrated["role"], migrated["action"], migrated["at"]) == (
        "system", "system", "migrated", reopened.now())
    assert migrated["details"]["status"] == {"before": "done", "after": "closed"}
    assert reopened.get(waiting)["status"] == "open"
    assert _code(reopened.claim, finished, "pia") == "item_closed"
    entries = len(reopened.journal())
    Store(store.path, clock=clock)  # opened again: the step has run, nothing more changes
    assert (len(reopened.journal()), reopened.get(finished)["version"]) == (entries, item["version"])


def test_anyone_may_comment_even_on_a_finished_task(store):
    task = store.add_task("hook", "A file arrived")
    store.claim(task, "ville")
    store.set_status(task, "ville", CLOSED)
    store.comment(task, "anna", "Checked after the fact.")
    assert store.journal(task)[-1]["details"] == {"body": "Checked after the fact."}
    assert store.journal(task)[-1]["role"] == "approver"

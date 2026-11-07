"""Protected ticket types (docs/governed-execution.md): opt-in, persistent, and not bypassable.

`Flights` stands in for an execution layer. An approval opens one flight (an external execution with its id,
fixed at approval). While a flight is in the air or its landing is unknown, the ticket may not end; it is
finished only once the flight has landed. Nothing here leaves the process.
"""

import sqlite3
from datetime import timedelta

import pytest

from datum.record import queue
from datum.record.store import CLOSED, FINISHED, RecordError, Store

TYPE = "ops.flight"
FLIGHTS = """CREATE TABLE IF NOT EXISTS flights (
    number INTEGER PRIMARY KEY REFERENCES items(number),
    execution_id TEXT NOT NULL,
    state TEXT NOT NULL);"""


class Flights:
    name = "test.flights@1"

    def __init__(self, store, *, explode_after_insert=False):
        store.ensure(FLIGHTS)
        self.calls = []
        self.explode_after_insert = explode_after_insert

    def approve(self, db, item, proposal, approver, attestation):
        self.calls.append(("approve", proposal["action"], approver))
        if proposal["action"] == "accept":
            return None                                     # the default: the approval finishes the ticket
        if (attestation or {}).get("digest") != proposal["payload"].get("digest"):
            raise RecordError("digest_mismatch", "approve what you were shown")
        db.execute("INSERT INTO flights VALUES (?,?,?)", (item["number"], f"X-{item['number']}", "approved"))
        if self.explode_after_insert:
            raise RuntimeError("the process died inside the approval")
        return {"status": "open"}

    def reject(self, db, item, proposal, approver, reason):
        self.calls.append(("reject", proposal["action"], approver))

    def check_end(self, db, item, status, actor):
        row = db.execute("SELECT state FROM flights WHERE number=?", (item["number"],)).fetchone()
        state = row[0] if row else None
        if state in ("in_flight", "unknown"):
            raise RecordError("execution_unresolved", f"#{item['number']}: the execution is {state}")
        if status == FINISHED and state != "landed":
            raise RecordError("not_verified", f"#{item['number']} is finished only after the execution landed")


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _ticket(store, type_=TYPE):
    with store.transaction() as db:
        return store.create_item(db, "hook", "task", type_, "Replace the banner", status="open")


def _proposed(store, *, type_=TYPE, by="ville", action="execute", digest="D1"):
    number = _ticket(store, type_)
    store.claim(number, by)
    queue.propose(store, number, by, action, "validated", payload={"digest": digest})
    return number


def _flight(store, number, state):
    with store.transaction() as db:
        db.execute("UPDATE flights SET state=? WHERE number=?", (state, number))


def _finish_decision(store, number, approver="anna"):
    """A direct finish through `update`, with a decision document, as Store.finish writes one."""
    with store.transaction() as db:
        store.take(db, number, approver, "approver")
        doc = store.document(db, approver, "decision", "Finished", "done", about=number, role="approver",
                             data={"decision": FINISHED, "ticket": number, "approver": approver, "reason": "done"})
        store.update(db, number, approver, role="approver", note={"decision": doc}, status=FINISHED)


@pytest.fixture
def flights(store):
    protection = Flights(store)
    store.protect(TYPE, protection, by="anna")
    return protection


# -- opting in -------------------------------------------------------------------------------------------------------

def test_nothing_is_protected_until_an_approver_protects_a_type(store):
    assert store.protected_types() == []
    store.add_user("approval-agent", ["worker"], kind="agent")
    assert _code(store.protect, TYPE, Flights(store), by="ville") == "role_missing"
    assert _code(store.protect, TYPE, Flights(store), by="approval-agent") == "agent_approver"
    assert _code(store.protect, TYPE, Flights(store), by="hook") == "agent_approver"
    store.protect(TYPE, Flights(store), by="anna")
    [row] = store.protected_types()
    assert (row["type"], row["protection"], row["protected_by"]) == (TYPE, Flights.name, "anna")
    entry = [e for e in store.journal() if e["action"] == "type_protected"][-1]
    assert (entry["item"], entry["actor"], entry["details"]) == (None, "anna", {"type": TYPE, "protection": Flights.name})


def test_a_protection_is_permanent_and_never_replaced(tmp_path, store, flights, clock):
    other = type("Other", (), {"name": "someone.else@1"})()
    assert _code(store.protect, TYPE, other, by="anna") == "protection_conflict"
    store.protect(TYPE, flights, by="pia")                       # the same name again: only attached
    assert len([e for e in store.journal() if e["action"] == "type_protected"]) == 1
    db = sqlite3.connect(store.path, isolation_level=None)
    for sql in ("DELETE FROM protected_types", "UPDATE protected_types SET protection = 'none'"):
        with pytest.raises(sqlite3.DatabaseError):
            db.execute(sql)
    reopened = Store(store.path, clock=clock)
    assert [r["type"] for r in reopened.protected_types()] == [TYPE]
    assert _code(reopened.attach_protection, TYPE, other) == "protection_conflict"
    assert _code(reopened.attach_protection, "ops.other", Flights(reopened)) == "not_protected"


# -- fail closed ---------------------------------------------------------------------------------------------------------

def test_a_store_without_the_protection_attached_refuses_rather_than_skips(store, flights, clock):
    number = _proposed(store)
    plain = store.add_task("hook", "an ordinary ticket")
    store.claim(plain, "ville")
    queue.propose(store, plain, "ville", "import", "fits")
    restarted = Store(store.path, clock=clock)                  # a new process that did not attach it
    assert _code(queue.approve, restarted, number, "anna", "ok", attestation={"digest": "D1"}) == \
        "protection_unavailable"
    assert _code(queue.reject, restarted, number, "anna", "no") == "protection_unavailable"
    assert [e["action"] for e in restarted.journal(number)][-1] == "rejection_refused"
    assert queue.approve(restarted, plain, "anna", "ordinary tickets are unaffected")["status"] == FINISHED
    restarted.attach_protection(TYPE, Flights(restarted))
    assert queue.approve(restarted, number, "anna", "ok", attestation={"digest": "D1"})["status"] == "open"


def test_ending_an_unattached_protected_ticket_is_refused(store, flights, clock):
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    restarted = Store(store.path, clock=clock)
    assert _code(restarted.finish, number, "anna", "done") == "protection_unavailable"
    restarted.claim(number, "ville")
    assert _code(restarted.close, number, "ville", "abandoned") == "protection_unavailable"


# -- approval cannot bypass the protection -------------------------------------------------------------------------------

def test_a_callers_effect_cannot_replace_the_protection(store, flights):
    number = _proposed(store)
    ran = []
    code = _code(queue.approve, store, number, "anna", "ok", effect=lambda db, item, p: ran.append(1))
    assert code == "protected_type" and ran == [] and flights.calls == []
    assert store.get(number)["status"] == "needs_input"
    assert [e["action"] for e in store.journal(number)][-1] == "approval_refused"
    assert _code(queue.reject, store, number, "anna", "no", effect=lambda db, item, p: None) == "protected_type"


def test_the_protection_decides_every_approval_with_what_the_approver_attests(store, flights):
    number = _proposed(store)
    assert _code(queue.approve, store, number, "anna", "ok") == "digest_mismatch"
    assert _code(queue.approve, store, number, "anna", "ok", attestation={"digest": "D2"}) == "digest_mismatch"
    assert store.get(number)["status"] == "needs_input"
    item = queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    assert item["status"] == "open" and "proposal" not in item["data"]
    assert flights.calls[-1] == ("approve", "execute", "anna")
    [decision] = store.documents_about(number, "decision")
    assert decision["data"]["decision"] == "approved"


def test_ordinary_self_approval_is_unchanged_and_left_to_the_protection(store, flights):
    number = _proposed(store, by="pia")
    assert queue.approve(store, number, "pia", "drafted and confirmed", attestation={"digest": "D1"})["status"] == "open"


def test_a_rejection_runs_the_protection(store, flights):
    number = _proposed(store)
    item = queue.reject(store, number, "anna", "not this week")
    assert item["status"] == "open" and flights.calls[-1] == ("reject", "execute", "anna")


# -- ending a ticket cannot bypass the protection -------------------------------------------------------------------------

@pytest.mark.parametrize("state, code", [("approved", "not_verified"), ("in_flight", "execution_unresolved"),
                                         ("unknown", "execution_unresolved")])
def test_finishing_is_refused_until_the_execution_has_landed(store, flights, state, code):
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    _flight(store, number, state)
    assert _code(store.finish, number, "anna", "done") == code
    assert _code(_finish_decision, store, number) == code         # Store.update directly, with a decision
    assert store.get(number)["status"] == "open"
    assert store.documents_about(number, "decision")[-1]["data"]["decision"] == "approved"   # nothing written
    _flight(store, number, "landed")
    assert store.finish(number, "anna", "verified")["status"] == FINISHED


def test_an_approval_that_would_finish_is_refused_until_the_execution_has_landed(store, flights):
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    store.claim(number, "ville")
    queue.propose(store, number, "ville", "accept", "landed, I think")
    assert _code(queue.approve, store, number, "anna", "accept") == "not_verified"
    assert store.get(number)["status"] == "needs_input"
    _flight(store, number, "landed")
    assert queue.approve(store, number, "anna", "accept")["status"] == FINISHED


@pytest.mark.parametrize("state", ["in_flight", "unknown"])
def test_closing_is_refused_while_the_execution_is_unresolved(store, flights, state):
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    _flight(store, number, state)
    store.claim(number, "ville")
    assert _code(store.close, number, "ville", "looks abandoned") == "execution_unresolved"
    assert store.get(number)["status"] == "open"
    _flight(store, number, "failed")                               # resolved: it did not land
    assert store.close(number, "ville", "the target refused the write")["status"] == CLOSED


def test_status_changes_that_do_not_end_a_ticket_are_unaffected(store, flights):
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    _flight(store, number, "in_flight")
    store.claim(number, "ville")
    assert store.set_status(number, "ville", "in_progress")["status"] == "in_progress"
    assert store.set_status(number, "ville", "open")["status"] == "open"
    assert _code(store.set_status, number, "ville", CLOSED) == "reason_required"     # the existing guard first
    assert _code(store.set_status, number, "ville", FINISHED) == "role_missing"      # only an approver finishes


# -- crash recovery and lease expiry ---------------------------------------------------------------------------------------

def test_a_failure_inside_the_protection_leaves_nothing_behind(store, clock):
    store.protect(TYPE, Flights(store, explode_after_insert=True), by="anna")
    number = _proposed(store)
    with pytest.raises(RuntimeError):
        queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    restarted = Store(store.path, clock=clock)
    restarted.attach_protection(TYPE, Flights(restarted))
    with restarted.reading() as db:
        assert db.execute("SELECT COUNT(*) FROM flights").fetchone()[0] == 0
    assert restarted.get(number)["status"] == "needs_input"
    assert queue.approve(restarted, number, "anna", "ok", attestation={"digest": "D1"})["status"] == "open"


def test_an_interrupted_execution_survives_lease_expiry_and_is_reconciled_with_its_id(store, flights, clock):
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    store.claim(number, "ville")
    _flight(store, number, "in_flight")                             # the executor dies here, holding the lease
    restarted = Store(store.path, clock=clock)
    restarted.attach_protection(TYPE, Flights(restarted))
    assert _code(restarted.claim, number, "pia") == "claim_conflict"
    clock.advance(days=2)
    restarted.claim(number, "pia")                                  # the lease ran out: another worker takes over
    assert _code(restarted.close, number, "pia", "looks abandoned") == "execution_unresolved"
    assert restarted.sweep(clock() + timedelta(days=60)) == []
    with restarted.reading() as db:
        assert db.execute("SELECT execution_id FROM flights WHERE number=?", (number,)).fetchone()[0] == f"X-{number}"
    _flight(restarted, number, "landed")                            # reconciled: the original execution landed
    queue.propose(restarted, number, "pia", "accept", "reconciled: landed")
    assert queue.approve(restarted, number, "anna", "verified")["status"] == FINISHED


# -- blockers ---------------------------------------------------------------------------------------------------------------

def test_blockers_names_every_unfinished_blocker_and_agrees_with_ready(store):
    dependent, first, second = (store.add_task("hook", t) for t in ("dependent", "first", "second"))
    assert store.blockers(dependent) == []
    store.link("ville", first, "blocks", dependent)
    store.link("ville", second, "blocks", dependent)
    assert store.blockers(dependent) == [{"number": first, "status": "open"}, {"number": second, "status": "open"}]
    assert dependent not in [t["number"] for t in store.ready()]
    store.claim(first, "ville")
    store.close(first, "ville", "went wrong")
    assert {b["number"]: b["status"] for b in store.blockers(dependent)} == {first: CLOSED, second: "open"}
    store.resolve_dependency(dependent, first, "anna", "not needed")
    store.finish(second, "anna", "done")
    assert store.blockers(dependent) == [] and dependent in [t["number"] for t in store.ready()]
    assert _code(store.blockers, 999) == "unknown_item"


def test_blockers_inside_a_transaction_sees_that_transactions_own_links(store):
    dependent, blocker = store.add_task("hook", "dependent"), store.add_task("hook", "blocker")
    with store.transaction() as db:
        store._link(db, "ville", blocker, "blocks", dependent)
        assert store.blockers(dependent, db=db) == [{"number": blocker, "status": "open"}]
        assert store.blockers(dependent) == []                       # not committed yet: another reader sees none
    assert store.blockers(dependent) == [{"number": blocker, "status": "open"}]


# -- ordinary workflows are untouched ------------------------------------------------------------------------------------------

def test_ordinary_tickets_keep_their_semantics_beside_a_protected_type(store, flights):
    task = store.add_task("hook", "an ordinary ticket")
    store.claim(task, "pia")
    queue.propose(store, task, "pia", "import", "fits")
    seen = []
    item = queue.approve(store, task, "pia", "self-approval as before", effect=lambda db, i, p: seen.append(1))
    assert item["status"] == FINISHED and seen == [1]
    other = store.add_task("hook", "another")
    store.claim(other, "ville")
    assert store.close(other, "ville", "cannot be done")["status"] == CLOSED
    assert flights.calls == []


def test_a_store_written_before_protection_existed_opens_and_works(store, clock):
    task = store.add_task("hook", "written by the older code")
    db = sqlite3.connect(store.path, isolation_level=None)          # remove what the older code never had
    for name in ("protected_types_kept", "protected_types_fixed"):
        db.execute(f"DROP TRIGGER {name}")
    db.execute("DROP TABLE protected_types")
    db.close()
    reopened = Store(store.path, clock=clock)
    assert reopened.protected_types() == []
    reopened.claim(task, "ville")
    queue.propose(reopened, task, "ville", "import", "fits")
    assert queue.approve(reopened, task, "anna", "as before")["status"] == FINISHED


# -- the database's own end guard ---------------------------------------------------------------------------------------------

def test_the_database_refuses_an_end_the_protection_did_not_agree_to(store, flights):
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    _flight(store, number, "landed")
    db = sqlite3.connect(store.path, isolation_level=None)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE items SET status = 'finished' WHERE number = ?", (number,))
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("INSERT INTO closing VALUES (?, 'ville', 'raw close')", (number,))
        db.execute("UPDATE items SET status = 'closed' WHERE number = ?", (number,))
    db.execute("DELETE FROM closing")
    assert store.get(number)["status"] == "open"
    assert store.finish(number, "anna", "verified")["status"] == FINISHED       # through the store, it ends


def test_code_that_skips_the_protection_cannot_end_a_protected_ticket(store, flights, monkeypatch):
    """What an older version of the store would do: never ask the protection. The database refuses."""
    number = _proposed(store)
    queue.approve(store, number, "anna", "ok", attestation={"digest": "D1"})
    _flight(store, number, "landed")
    monkeypatch.setattr(store, "protection", lambda db, item: None)
    with pytest.raises(sqlite3.DatabaseError):
        store.finish(number, "anna", "verified")
    store.claim(number, "ville")
    with pytest.raises(sqlite3.DatabaseError):
        store.close(number, "ville", "skip it")
    assert store.get(number)["status"] == "open"
    plain = store.add_task("hook", "ordinary")
    store.claim(plain, "ville")
    assert store.close(plain, "ville", "ordinary tickets end as before")["status"] == CLOSED

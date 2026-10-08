"""Consultations as tickets: one per call, opened to an agent, released back to open, every write
attributed; questions paged, with the open ones counted over all of them."""

import pytest

from babel.checks import Check
from babel.record import consultations as cons
from babel.record import queue
from babel.record.store import RecordError

# the clock and store fixtures are in conftest.py

SUBJECT = {"customer": "C-1", "machine": "M-1", "part": "P-1"}
PASS = Check(unsupported=(), leaks=(), dates=())


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _start(store, actor="ville"):
    return cons.start(store, actor, "Consultation: Customer one · M-1 · P-1", subject=SUBJECT)["number"]


def _answer(store, number, question="Lead time", actor="ville", **extra):
    fields = dict(facts="FACTS:\n- [lead_time] 7 days.", tools_run=["lead_time"], rule="a rule")
    fields.update(extra)
    return cons.answer(store, number, actor, question, f"{question} of P-1 for M-1", **fields)


def test_each_consultation_is_its_own_ticket_opened_to_the_agent(store):
    first, second = _start(store), _start(store, "pia")
    assert (first, second) == (1, 2)  # one number space, one ticket per consultation
    item = cons.get(store, first)
    assert (item["kind"], item["type"], item["status"], item["claimed_by"]) == (
        "task", "consultation", "in_progress", "ville")
    assert [(e["actor"], e["action"]) for e in store.journal(first)] == [
        ("ville", "created"), ("ville", "claimed"), ("ville", "opened")]
    created = store.journal(first)[0]["details"]
    assert created["type"] == "consultation"
    assert store.journal(first)[2]["details"] == {"status": {"before": "open", "after": "in_progress"}}


def test_released_unconcluded_a_consultation_goes_back_to_open(store):
    number = _start(store)
    released = cons.release(store, number, "ville")
    assert (released["status"], released["claimed_by"]) == ("open", None)
    assert store.journal(number)[-1]["action"] == "released"
    assert store.open_ticket(number, "pia")["status"] == "in_progress"  # the next agent takes it up


def test_every_write_needs_the_holders_claim_and_is_attributed(store):
    number = _start(store)
    assert _code(cons.person_fact, store, number, "pia", "stopped", "stopped", "machine stopped: yes") == \
        "claim_required"
    cons.person_fact(store, number, "ville", "stopped", "stopped", "machine stopped: yes (breakdown)")
    entry = store.journal(number)[-1]
    assert (entry["actor"], entry["role"], entry["action"], entry["details"]["fact"]) == (
        "ville", "worker", "person_answered", "stopped")
    assert cons.get(store, number)["data"]["person"]["stopped"]["by"] == "ville"
    other = store.add_task("hook", "A file arrived")
    store.claim(other, "ville")
    assert _code(cons.person_fact, store, other, "ville", "stopped", "stopped", "x") == "not_a_consultation"


def test_a_question_waits_for_the_person_and_is_answered_when_asked_again(store):
    number = _start(store)
    cons.ask_person(store, number, "ville", "Availability", "Availability of P-1 for M-1",
                    waiting_for="stopped", ask="Has M-1 stopped?")
    cons.ask_person(store, number, "ville", "Availability", "Availability of P-1 for M-1",
                    waiting_for="stopped", ask="Has M-1 stopped?")  # asked again: no second question
    assert [q["status"] for q in cons.get(store, number)["data"]["questions"]] == ["open"]
    assert _code(_answer, store, number, "Availability", uses=["stopped"]) == "person_fact_missing"
    cons.person_fact(store, number, "ville", "stopped", "stopped", "machine stopped: yes (breakdown)")
    item = _answer(store, number, "Availability", uses=["stopped"])
    first, second = item["data"]["questions"]
    assert (first["status"], first["answered_in"]) == ("answered", 2)
    assert second["from_person"] == ["machine stopped: yes (breakdown), answered by ville"]
    assert cons.latest_answer(item) == second


def test_open_questions_are_counted_over_all_questions_not_the_page(store):
    # backlog C13: the lab's get_case took open questions from the paged slice
    number = _start(store)
    cons.ask_person(store, number, "ville", "Availability", "Availability of P-1 for M-1",
                    waiting_for="stopped", ask="Has M-1 stopped?")
    for _ in range(23):
        _answer(store, number)
    cons.ask_person(store, number, "ville", "Service demand", "Service demand for M-1",
                    waiting_for="machine", ask="Which machine?")
    first, second = cons.view(store, number), cons.view(store, number, offset=cons.PAGE)
    assert ([q["n"] for q in first["questions"]], first["next_offset"]) == (list(range(1, 21)), 20)
    assert ([q["n"] for q in second["questions"]], second["next_offset"]) == (list(range(21, 26)), None)
    for page in (first, second):
        assert [q["n"] for q in page["open_questions"]] == [1, 25]
        assert len(page["answered_questions"]) == 23 and page["total"] == 25
    # what the paged slice alone would have said: each page misses an open question
    assert [q["n"] for q in first["questions"] if q["status"] == "open"] == [1]
    assert [q["n"] for q in second["questions"] if q["status"] == "open"] == [25]
    assert "Open questions, of all 25: 1 (Has M-1 stopped?), 25 (Which machine?)" in cons.view_text(second)
    assert _code(cons.view, store, number, limit=cons.PAGE + 1) == "invalid_argument"


def test_a_proposed_reply_waits_for_an_approver_and_nothing_is_sent(store):
    number = _start(store)
    _answer(store, number)
    cons.record_check(store, number, "ville", 1, "draft", Check(unsupported=("9",)))
    item = cons.propose_reply(store, number, "ville", answer_text="CUSTOMER ANSWER:\n7 days.",
                              customer_answer="7 days.", against=1, check=PASS, reason="Reply; checks pass")
    assert (item["status"], item["claimed_by"]) == ("needs_input", None)
    [waiting] = queue.pending(store)
    assert (waiting["number"], waiting["action"], waiting["proposed_by"]) == (number, "reply", "ville")
    assert waiting["payload"]["customer_answer"] == "7 days." and waiting["payload"]["check"] == 2
    assert not any("sent" in e["action"] for e in store.journal())
    assert _code(queue.approve, store, number, "ville", "fine") == "role_missing"
    assert _code(queue.approve, store, number, "anna", " ") == "invalid_argument"
    assert "Reply: the reply waits in the approval queue" in cons.view_text(cons.view(store, number))
    assert queue.approve(store, number, "anna", "Checked against the facts")["status"] == "done"
    card = cons.view_text(cons.view(store, number))
    assert card.splitlines()[0] == f"#{number} consultation · closed"
    [decision] = store.documents_about(number, "decision")
    assert card.splitlines()[-1] == f"Reply: approved by anna (decision #{decision['number']}): Checked against the facts"


def test_a_consultation_with_no_questions_says_so(store):
    card = cons.view_text(cons.view(store, _start(store)))
    assert card.splitlines()[2:] == ["", "From the person: nothing yet", "", "Questions: none asked yet",
                                     "Checks: none run", "Reply: nothing queued yet: propose_reply queues the "
                                     "reply for an approver, a named person with the approver role. Nothing is sent"]


def test_the_receipt_says_what_was_asked_run_applied_checked_not_known_and_who_approves(store):
    number = _start(store)
    cons.person_fact(store, number, "ville", "stopped", "stopped", "machine stopped: yes (breakdown)")
    item = _answer(store, number, "Availability", uses=["stopped"], tools_run=["a", "b"],
                   rule="breakdown → fastest option", not_known=["competing claims on PO-1 are not modelled"])
    entry = cons.latest_answer(item)
    assert dict(cons.receipt(item, entry)) == {
        "asked of the person": "machine stopped: yes (breakdown), answered by ville",
        "tools run": "a · b",
        "rule applied": "breakdown → fastest option",
        "checks": "not run yet: check(consultation, answer) runs them on a draft",
        "not known": "competing claims on PO-1 are not modelled",
        "needs approval": "nothing queued yet: propose_reply queues the reply for an approver, a named person "
                          "with the approver role. Nothing is sent",
    }
    item = cons.propose_reply(store, number, "ville", answer_text="a", customer_answer="a", against=entry["n"],
                              check=PASS, reason="Reply")
    lines = dict(cons.receipt(item, entry))
    assert lines["checks"] == ("pass: numbers: all in the facts · dates: all in the facts, compared as whole "
                               "dates · other customers: none named in the customer answer (on the reply as "
                               "proposed)")
    assert lines["needs approval"].startswith(f"the reply waits in the approval queue on #{number}")


def test_the_status_filter_uses_the_owners_three_statuses(store):
    open_one, working, closed = _start(store), _start(store), _start(store)
    cons.release(store, open_one, "ville")
    store.set_status(closed, "ville", "done")
    assert [t["number"] for t in cons.tickets(store, "open")] == [open_one]
    assert [t["number"] for t in cons.tickets(store, "in_progress")] == [working]
    assert [t["number"] for t in cons.tickets(store, "closed")] == [closed]
    assert _code(cons.tickets, store, "needs_input") == "invalid_argument"

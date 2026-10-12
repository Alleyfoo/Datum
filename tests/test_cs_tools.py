"""The customer-service tools for one call: a ticket per consultation, the person asked and never
guessed, the answer checked, the reply proposed and never sent."""

import ast
from pathlib import Path

import pytest

import babel.checks.answers
import babel.mcp.registry
import babel.record.consultations
import domains.spare_parts.customer_service
from babel.mcp import ToolError
from babel.record import queue
from babel.record.store import CLOSED, RecordError
from cs_briefs import ANSWERS, REPLY
from domains.spare_parts import tools
from domains.spare_parts.customer_service import build
from domains.spare_parts.data import demo

# the clock and store fixtures are in conftest.py

DATA = demo()
CLAIM = "competing claims on PO-4718 are not modelled: SC-01 is overdue for 3 pcs, also served from FI"


@pytest.fixture
def role(store):
    return build(store, DATA, actor="ville")


def _flat(text: str) -> str:
    """The text with its line wrapping undone, to find a sentence the receipt wrapped."""
    return " ".join(text.split())


def _code(call, *args, **kwargs):
    with pytest.raises(RecordError) as error:
        call(*args, **kwargs)
    return error.value.code


def _open(role):
    role.call("open_consultation", {"customer": "C-300", "machine": "CH-02", "part": "SP-1601"})
    return 1


#: the slice's tools, in the order the role lists them first
SLICE_TOOLS = ["search", "open_consultation", "stopped", "ask", "check", "propose_reply"]


def test_the_role_has_the_six_tools_and_cannot_send_or_approve(role):
    assert role.names()[:6] == SLICE_TOOLS
    assert [t.name for t in role.tools() if not t.writes] == ["search"]
    for word in ("approve", "verdict", "send", "reject", "decide"):  # the lab's test_mcp, on this role
        assert not any(word in name for name in role.names()), word
    assert all(t.function.__doc__ for t in role.tools())


def test_a_consultation_is_its_own_ticket_in_progress_with_the_agent(store, role):
    out = role.call("open_consultation", {"customer": "Pulp mill customer", "machine": "CH-02", "part": "SP-1601"})
    assert out.startswith("Consultation #1 opened: in_progress, with ville. It is this call's ticket.\n"
                          "Consultation: Pulp mill customer · CH-02 Chip pile reclaim screw · "
                          "SP-1601 Screw flight section, 400 mm\n")
    item = store.get(1)
    assert (item["type"], item["status"], item["claimed_by"]) == ("consultation", "in_progress", "ville")
    assert item["data"]["subject"] == {"customer": "C-300", "machine": "CH-02", "part": "SP-1601"}
    role.call("open_consultation", {"customer": "C-300", "machine": "CH-02"})
    assert [i["number"] for i in store.items("task")] == [1, 2]  # one ticket per consultation
    assert [e["action"] for e in store.journal(1)] == ["created", "claimed", "opened"]


def test_a_consultation_names_a_real_customer_machine_and_part(role):
    for arguments, message in [
        ({"customer": "Nobody"}, "no customer"),
        ({"customer": "C-300", "machine": "BC-01"}, "has no machine 'BC-01'"),
        ({"customer": "C-300", "machine": "CH-02", "part": "SP-1301"}, "not on the parts list of CH-02"),
        ({"customer": "C-300", "part": "SP-1601"}, "a part needs its machine"),
    ]:
        with pytest.raises(ToolError, match=message):
            role.call("open_consultation", arguments)


def test_availability_without_the_persons_answer_returns_the_question_not_an_answer(store, role):
    number = _open(role)
    out = role.call("ask", {"consultation": number, "question": "Availability"})
    assert out.startswith("#1 question 1: Availability of SP-1601 for CH-02 waits for the person. "
                          "No answer is given without it.\n\nHas CH-02 stopped?")
    assert "FACTS:" not in out and "RECOMMENDED PLAN" not in out
    [question] = store.get(number)["data"]["questions"]
    assert (question["status"], question["waiting_for"]) == ("open", "stopped")
    assert "stopped" not in store.get(number)["data"]["person"]  # nothing was guessed


def test_the_persons_answer_is_recorded_and_attributed_and_decides_the_rule(store, role):
    number = _open(role)
    role.call("ask", {"consultation": number, "question": "Availability"})
    said = role.call("stopped", {"consultation": number, "state": "stopped"})
    assert said.startswith("Recorded on #1: CH-02 has stopped and waits for the part (breakdown), as ville")
    fact = store.get(number)["data"]["person"]["stopped"]
    assert (fact["value"], fact["by"], fact["text"]) == ("stopped", "ville", "machine stopped: yes (breakdown)")
    out = role.call("ask", {"consultation": number, "question": "Availability"})
    assert tools.availability(DATA, "CH-02", "SP-1601", "breakdown").render() in out
    assert "asked of the person   machine stopped: yes (breakdown), answered by ville" in out
    first, second = store.get(number)["data"]["questions"]
    assert (first["status"], first["answered_in"], second["status"]) == ("answered", 2, "answered")
    role.call("stopped", {"consultation": number, "state": "planned"})  # the person corrects it
    assert "company rule for planned service" in role.call("ask", {"consultation": number, "question": "Availability"})
    with pytest.raises(ToolError, match="must be one of stopped, planned"):
        role.call("stopped", {"consultation": number, "state": "maybe"})


def test_the_receipt_names_the_competing_claim_that_is_not_modelled(role):
    number = _open(role)
    role.call("stopped", {"consultation": number, "state": "stopped"})
    out = role.call("ask", {"consultation": number, "question": "Availability"})
    assert f"not known {CLAIM}" in _flat(out)
    assert f"not known {CLAIM}" in _flat(role.call("propose_reply", {"consultation": number, "answer": REPLY}))


def test_lead_time_and_service_demand_need_no_answer_from_the_person(role):
    number = _open(role)
    lead = role.call("ask", {"consultation": number, "question": "Lead time"})
    assert tools.lead_time_question(DATA, "CH-02", "SP-1601").render() in lead
    assert "asked of the person   nothing: this question needs no fact only the person knows" in lead
    service = role.call("ask", {"consultation": number, "question": "Service demand"})
    assert tools.service_demand(DATA, "CH-02").render() in service


def test_a_question_needs_what_it_is_about(role):
    role.call("open_consultation", {"customer": "C-300", "machine": "CH-02"})
    with pytest.raises(ToolError, match="Availability needs a part"):
        role.call("ask", {"consultation": 1, "question": "Availability"})
    assert "Service demand for CH-02" in role.call("ask", {"consultation": 1, "question": "Service demand"})
    role.call("open_consultation", {"customer": "C-300"})
    with pytest.raises(ToolError, match="has no machine"):
        role.call("ask", {"consultation": 2, "question": "Service demand"})


def test_check_passes_a_reply_copied_from_the_facts_and_keeps_the_result(store, role):
    number = _open(role)
    with pytest.raises(ToolError, match="no answer yet"):
        role.call("check", {"consultation": number, "answer": REPLY})
    role.call("stopped", {"consultation": number, "state": "stopped"})
    role.call("ask", {"consultation": number, "question": "Availability"})
    out = role.call("check", {"consultation": number, "answer": REPLY})
    assert out.splitlines()[0] == "checks on #1 against question 1 (Availability of SP-1601 for CH-02): pass"
    [kept] = store.get(number)["data"]["checks"]
    assert (kept["against"], kept["ok"], kept["answer"], kept["by"]) == (1, True, REPLY, "ville")


def test_check_fails_another_customer_named_and_a_date_rebuilt_from_pieces(role):
    number = _open(role)
    role.call("stopped", {"consultation": number, "state": "stopped"})
    role.call("ask", {"consultation": number, "question": "Availability"})
    leak = role.call("check", {"consultation": number, "answer": ANSWERS["other_customer"]})
    assert leak.splitlines()[0].endswith(": fail")
    assert "other customers   named in the customer answer: Sawmill customer" in leak
    rebuilt = role.call("check", {"consultation": number, "answer": ANSWERS["rebuilt_date"]})
    assert "dates             not in the facts: 2026-02-10" in rebuilt


def test_propose_reply_queues_it_for_an_approver_and_sends_nothing(store, role):
    number = _open(role)
    role.call("stopped", {"consultation": number, "state": "stopped"})
    role.call("ask", {"consultation": number, "question": "Availability"})
    out = role.call("propose_reply", {"consultation": number, "answer": REPLY})
    assert out.startswith("Reply proposed on #1: it waits for an approver. Nothing has been sent.")
    item = store.get(number)
    assert (item["status"], item["claimed_by"]) == ("needs_input", None)
    [waiting] = queue.pending(store)
    assert (waiting["number"], waiting["action"], waiting["proposed_by"]) == (number, "reply", "ville")
    assert waiting["payload"]["customer_answer"].startswith("We have no screw flight sections in stock.")
    assert waiting["reason"].endswith("(Availability of SP-1601 for CH-02); checks pass")
    assert not any("sent" in e["action"] for e in store.journal())
    # the proposal needs an approver: a named person with the role, and a reason
    assert _code(queue.approve, store, number, "ville", "looks right") == "role_missing"
    assert _code(queue.approve, store, number, "anna", "") == "invalid_argument"
    closed = queue.approve(store, number, "anna", "Checked against the facts")
    assert closed["status"] == CLOSED
    [decision] = store.documents_about(number, "decision")
    assert (decision["data"]["approver"], decision["data"]["action"]) == ("anna", "reply")


def test_a_released_consultation_goes_back_to_open(store, role):
    number = _open(role)
    babel.record.consultations.release(store, number, "ville", "The customer will call back")
    assert store.get(number)["status"] == "open"
    assert role.call("search", {"status": "open"}).startswith("search status open: 1 ticket, shown")
    assert _code(role.call, "ask", {"consultation": number, "question": "Lead time"}) == "claim_required"


#: the modules a tool runs: none may reach a model, the network, another process, a clock or chance
#: (the store stamps its journal with the time; no tool's text carries it)
TOOL_MODULES = [domains.spare_parts.customer_service, babel.record.consultations, babel.checks.answers,
                babel.mcp.registry, tools]
FORBIDDEN_IMPORTS = {"urllib", "http", "socket", "ssl", "requests", "httpx", "subprocess", "multiprocessing",
                     "random", "secrets", "time", "datetime.datetime", "uuid", "ollama", "openai", "anthropic",
                     "mcp"}


@pytest.mark.parametrize("module", TOOL_MODULES, ids=lambda m: m.__name__)
def test_no_tool_calls_a_model(module):
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        for name in names:
            assert name.split(".")[0] not in FORBIDDEN_IMPORTS and name not in FORBIDDEN_IMPORTS, name

"""search: the 0/1/many rule over customers, machines and parts, and tickets by status."""

import pytest

from babel.checks import Check
from babel.mcp import ToolError
from babel.record import consultations as cons
from babel.record import queue
from domains.spare_parts.customer_service import build
from domains.spare_parts.data import demo
from domains.spare_parts.views import machine_card, plant_view

# the clock and store fixtures are in conftest.py

DATA = demo()


@pytest.fixture
def search(store):
    return build(store, DATA, actor="ville")["search"].function


def test_several_matches_are_listed_and_none_is_opened(search):
    out = search("screw")
    assert out == "\n".join([
        'search "screw": 4 matches. Which one?',
        "",
        " 1  machine  SC-01    Screen feed screw          Sawmill customer       ▲",
        " 2  machine  SC-11    Fuel screen screw          Power plant customer   ▲",
        " 3  machine  CH-02    Chip pile reclaim screw    Pulp mill customer     ✖",
        " 4  part     SP-1601  Screw flight section, 400 mm",
        "",
        "The person picks one; search its id to open it.",
    ])
    assert machine_card(DATA, "CH-02") not in out


def test_one_match_opens_its_card(search):
    out = search("reclaim screw")
    assert out.startswith('search "reclaim screw": 1 match, opened.\n\n' + machine_card(DATA, "CH-02") + "\n\n")
    assert 'open_consultation("C-300", "CH-02", part)' in out


def test_no_match_is_reported_and_nothing_is_guessed(search):
    assert search("zzz") == ('search "zzz": no match among customers, machines and parts. Nothing is opened; '
                             "ask the person for an id or other words.")


def test_an_id_typed_exactly_is_one_match(search):
    assert search("c-300").startswith('search "c-300": 1 match, opened.\n\n' + plant_view(DATA, "C-300"))
    part = search("SP-1601")
    assert part.startswith('search "SP-1601": 1 match, opened.\n\nSP-1601 Screw flight section, 400 mm')
    assert " 3  CH-02    Pulp mill customer       4  due 2026-11-01" in part.splitlines()


def test_matches_with_the_same_beginning_are_told_apart(search):
    lines = search("bearing").splitlines()
    assert lines[2:5] == [" 1  part     SP-1301  Spherical roller bearing 22216",
                          " 2  part     SP-1311  Spherical roller bearing 22216, alternative make",
                          " 3  part     SP-1303  Spherical roller bearing 22220"]


def test_a_search_needs_words_or_a_status(search):
    with pytest.raises(ToolError, match="needs words"):
        search("  ")
    with pytest.raises(ToolError, match="status must be one of open, in_progress, closed"):
        search(status="needs_input")


def _tickets(store):
    """One consultation in each state: open (released), in progress, waiting for an approver, closed."""
    numbers = {}
    for state in ("open", "in_progress", "waiting", "closed"):
        numbers[state] = cons.start(store, "ville", f"Consultation: {state} line", subject={})["number"]
    cons.release(store, numbers["open"], "ville")
    for state in ("waiting", "closed"):
        cons.answer(store, numbers[state], "ville", "Lead time", "Lead time", facts="FACTS:", tools_run=["lead_time"],
                    rule="a rule")
        cons.propose_reply(store, numbers[state], "ville", answer_text="7 days.", customer_answer="7 days.",
                           against=1, check=Check(unsupported=()),
                           reason="Reply")
    queue.approve(store, numbers["closed"], "anna", "Checked against the facts")
    return numbers


def test_the_status_filter_lists_tickets_of_that_status_only(store, search):
    numbers = _tickets(store)
    out = search(status="open")
    assert out.startswith("search status open: 1 ticket, shown; viewing it changes nothing.\n\n"
                          f"#{numbers['open']} consultation · open\nConsultation: open line")
    working = search(status="in_progress")
    assert working.startswith(f"search status in_progress: 1 ticket, shown; viewing it changes nothing.\n\n"
                              f"#{numbers['in_progress']} consultation · in_progress, with ville")
    closed = search(status="closed")
    assert closed.startswith(f"search status closed: 1 ticket, shown; viewing it changes nothing.\n\n"
                             f"#{numbers['closed']} consultation · closed")
    # waiting for an approver is in the approval queue, not under these three statuses (owner answer 3)
    assert all(f"#{numbers['waiting']} " not in text for text in (out, working, closed))


def test_several_tickets_are_listed_and_text_narrows_them(store, search):
    first = cons.start(store, "ville", "Consultation: Pulp mill customer · CH-02", subject={})["number"]
    second = cons.start(store, "pia", "Consultation: Sawmill customer · BC-01", subject={})["number"]
    assert search(status="in_progress") == "\n".join([
        "search status in_progress: 2 tickets. Which one?",
        "",
        f" 1  #{first:<4} consultation  Consultation: Pulp mill customer · CH-02  ·  in_progress, with ville",
        f" 2  #{second:<4} consultation  Consultation: Sawmill customer · BC-01  ·  in_progress, with pia",
    ])
    assert search("ch-02", status="in_progress").startswith(
        'search "ch-02" with status in_progress: 1 ticket, shown')


def test_a_status_with_no_ticket_is_reported(store, search):
    assert search(status="closed") == "search status closed: no ticket."
    cons.start(store, "ville", "Consultation: Pulp mill customer · CH-02", subject={})
    assert search("zzz", status="in_progress") == 'search "zzz" with status in_progress: no ticket.'


def test_search_writes_nothing(store, search):
    _tickets(store)
    before = (store.journal(), store.items())
    for text in ("screw", "reclaim screw", "zzz", "SP-1601"):
        search(text)
    for status in ("open", "in_progress", "closed"):
        search(status=status)
    assert (store.journal(), store.items()) == before

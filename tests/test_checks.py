"""The answer checks, against the lab's own results on the same answers.

golden/cs/lab_reference/checks.txt holds what the lab's check_answer said about each answer in
tests/cs_briefs.py (captured once from Parts-Service-Desk at 46c859a). The port agrees with it
except where the lab compared the pieces of dates (backlog C13), and those cases are listed here.
"""

import re
from pathlib import Path

from datum.checks import Check, check_answer, customer_part, dates_in, describe, numbers_in
from cs_briefs import ANSWERS, GOLDEN, checks
from domains.spare_parts import tools
from domains.spare_parts.data import demo

LAB = Path(__file__).parent / "golden" / "cs" / "lab_reference" / "checks.txt"
DATA = demo()
BRIEF = tools.availability(DATA, *GOLDEN)
FACTS = BRIEF.render()


def _port(answer, brief):
    return check_answer(answer, brief.render(), brief.confidential)


def _lab_lines():
    return dict(line.split(": ", 1) for line in LAB.read_text(encoding="utf-8").splitlines())


def _fragments(text):
    """The lab's numbers_in (desk/expert.py): every run of digits, dates split into their pieces."""
    return {n.replace(",", ".").lstrip("0") or "0" for n in re.findall(r"\d+(?:[.,]\d+)?", text)}


#: where comparing whole dates changes the lab's result, and what the port finds instead
WHOLE_DATES = {
    "rebuilt_date": "ok=False unsupported=() leaks=()",   # and dates=('2026-02-10',)
    "date_piece": "ok=False unsupported=('22',) leaks=()",
    "invented_number": "ok=False unsupported=('6', '9') leaks=()",
}


def test_the_port_agrees_with_the_lab_except_where_it_compares_whole_dates():
    lab = _lab_lines()
    port = dict(line.split(": ", 1) for line in checks(_port, tools, DATA).splitlines())
    assert sorted(port) == sorted(lab) == sorted(ANSWERS)
    assert {name: port[name] for name in port if port[name] != lab[name]} == WHOLE_DATES


def test_a_date_rebuilt_from_the_pieces_of_a_fact_date_fails():
    # 2026-10-02 is the company's date in the facts; 2026-02-10 is made of its pieces
    answer = ANSWERS["rebuilt_date"]
    assert "2026-10-02" in FACTS and "2026-02-10" not in FACTS
    assert _fragments(answer) <= _fragments(FACTS)  # the lab's comparison finds nothing wrong
    assert _lab_lines()["rebuilt_date"].startswith("ok=True")
    found = _port(answer, BRIEF)
    assert (found.ok, found.dates, found.unsupported) == (False, ("2026-02-10",), ())


def test_a_date_copied_from_the_facts_passes():
    found = _port("CUSTOMER ANSWER:\nThe full set of 4 arrives on Thu 2026-10-22.\n", BRIEF)
    assert found == Check(unsupported=(), leaks=(), dates=()) and found.ok


def test_every_number_in_the_answer_must_be_in_the_facts():
    found = _port(ANSWERS["invented_number"], BRIEF)
    assert found.unsupported == ("6", "9")  # 9 is only a piece of 2026-09-01 in the facts
    assert _port(ANSWERS["reply"], BRIEF).ok


def test_another_customer_named_in_the_reply_fails():
    assert _port(ANSWERS["other_customer"], BRIEF).leaks == ("Sawmill customer",)
    assert _port(ANSWERS["other_machine"], BRIEF).leaks == ("SC-01",)
    assert not _port(ANSWERS["other_customer"], BRIEF).ok


def test_other_customers_may_be_named_in_the_internal_part():
    assert _port(ANSWERS["others_named_internally"], BRIEF).ok


def test_without_a_customer_heading_the_whole_answer_is_the_customers():
    assert customer_part(ANSWERS["no_sections"]) == ANSWERS["no_sections"]
    assert _port(ANSWERS["no_sections"], BRIEF).leaks == ("Sawmill customer",)


def test_dates_are_whole_tokens_and_numbers_come_from_outside_them():
    text = "PO-4718: 4 x SP-1601 due Thu 2026-10-22 (1,5 days; 007 left)"
    assert dates_in(text) == {"2026-10-22"}
    assert numbers_in(text) == {"4718", "4", "1601", "1.5", "7"}
    assert numbers_in("on 2026-10-22") == set() and dates_in("20261022 or 2026-10") == set()


def test_the_check_reads_as_lines_for_a_receipt():
    assert describe(_port(ANSWERS["reply"], BRIEF)) == [
        ("numbers", "all in the facts"),
        ("dates", "all in the facts, compared as whole dates"),
        ("other customers", "none named in the customer answer"),
    ]
    found = Check(unsupported=("6", "9"), leaks=("Sawmill customer",), dates=("2026-02-10",))
    assert describe(found) == [
        ("numbers", "not in the facts: 6, 9"),
        ("dates", "not in the facts: 2026-02-10"),
        ("other customers", "named in the customer answer: Sawmill customer"),
    ]

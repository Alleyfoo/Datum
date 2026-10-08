"""The service rules behind the customer-service answers, checked against the lab's own output.

golden/cs/lab_reference/ holds the lab's briefs, captured once from Parts-Service-Desk at 46c859a
(scripts/capture_lab_cs_reference.py) and never regenerated. The port must give the same text, fact
for fact, for every question on every part of every machine.

The rule tests below are the lab's own (its tests/test_desk.py), run against the port.
"""

import difflib
from pathlib import Path

import pytest

from cs_briefs import GOLDEN, briefs
from domains.spare_parts import tools
from domains.spare_parts.data import demo

LAB = Path(__file__).parent / "golden" / "cs" / "lab_reference"
BRIEF_NAMES = sorted(path.stem for path in LAB.glob("*.txt") if path.stem != "checks")

DATA = demo()


@pytest.fixture(scope="module")
def port():
    return briefs(tools, DATA)


def _same(expected: str, actual: str, label: str) -> None:
    if actual == expected:
        return
    diff = "\n".join(difflib.unified_diff(expected.splitlines(), actual.splitlines(),
                                          f"{label} (lab)", f"{label} (port)", lineterm=""))
    pytest.fail(f"{label} differs from the lab's text:\n{diff or 'the line ends differ'}", pytrace=False)


def test_the_port_renders_every_brief_the_lab_was_captured_with(port):
    assert sorted(port) == BRIEF_NAMES


@pytest.mark.parametrize("name", BRIEF_NAMES)
def test_the_port_gives_the_lab_text(port, name):
    _same((LAB / f"{name}.txt").read_text(encoding="utf-8"), port[name], f"lab_reference/{name}.txt")


def test_the_golden_case_takes_PO_4718_by_the_breakdown_rule():
    brief = tools.availability(DATA, *GOLDEN)
    assert brief.render() == (LAB / "availability_CH-02_SP-1601_breakdown.txt").read_text(encoding="utf-8")
    [plan] = [f.text for f in brief.facts if f.tool == "recommended_plan"]
    assert plan == ("RECOMMENDED PLAN (company rule for a breakdown: fastest option): "
                    "from purchase order PO-4718, arrives Thu 2026-10-22.")


# -- the lab's rule tests ------------------------------------------------------------


def plan(machine, part, situation):
    brief = tools.availability(DATA, machine, part, situation)
    return next(f.text for f in brief.facts if f.tool == "recommended_plan")


def facts_of(brief, tool):
    return [f.text for f in brief.facts if f.tool == tool]


def test_breakdown_takes_the_fastest_option_and_restocks_what_it_starves():
    text = plan("BC-01", "SP-1301", "breakdown")
    assert "transfer from SE stock" in text
    assert "also order 4 pcs today to restock SE" in text


def test_planned_service_skips_an_option_that_starves_another_customer():
    text = plan("BC-01", "SP-1301", "planned")
    assert text.split(":")[1].strip().startswith("earliest option")
    assert "new supplier order" in text
    assert "faster option (transfer from SE stock" in text


def test_no_conflict_means_no_restock_note():
    text = plan("BC-02", "SP-1203", "breakdown")  # replaced on failure: nothing scheduled
    assert "transfer from SE stock" in text
    assert "restock" not in text


def test_nothing_in_stock_falls_back_to_a_new_order():
    assert "new supplier order, arrives Fri 2027-01-08" in plan("BC-01", "SP-1501", "breakdown")


def test_a_substitute_short_of_the_full_set_says_so():
    brief = tools.availability(DATA, "BC-01", "SP-1301", "breakdown")
    assert "not enough for the full set: at most 3 of the 4" in facts_of(brief, "substitutes")[0]


def test_the_conflict_names_who_is_starved_internally():
    brief = tools.availability(DATA, "BC-01", "SP-1301", "breakdown")
    conflict = next(f.text for f in brief.facts if f.text.startswith("CONFLICT"))
    assert "FR-01" in conflict and "shortfall of 4 pcs" in conflict


def test_the_situation_must_come_from_the_person():
    with pytest.raises(ValueError):
        tools.availability(DATA, "BC-01", "SP-1301", "whenever")
    assert tools.availability(DATA, "BC-01", "SP-1301", "planned").facts[0].tool == "reported_by_person"


def test_every_tool_in_the_recipe_contributed_a_fact():
    brief = tools.availability(DATA, "BC-01", "SP-1301", "breakdown")
    assert set(brief.tools_run) <= {f.tool for f in brief.facts}


def test_service_demand_lists_overdue_and_due_parts_first():
    schedule = facts_of(tools.service_demand(DATA, "BC-01"), "service_schedule")
    assert schedule[0].startswith("SP-1401") and "overdue since" in schedule[0]
    assert schedule[1].startswith("SP-1301") and "due Mon 2026-11-02" in schedule[1]


def test_planned_service_does_not_take_stock_another_customer_needs():
    supply = facts_of(tools.service_demand(DATA, "BC-01"), "service_supply")
    bearing = next(t for t in supply if t.startswith("SP-1301"))
    assert "purchase order PO-4711" in bearing and "SE" not in bearing


def test_the_customer_who_needs_the_stock_gets_it():
    supply = facts_of(tools.service_demand(DATA, "FR-01"), "service_supply")
    assert any(t.startswith("SP-1301: reserve 4 from SE stock") for t in supply)


def test_a_visit_never_falls_on_a_weekend():
    plans = facts_of(tools.service_demand(DATA, "BC-02"), "service_plan")
    assert "service visit on Mon 2026-11-02" in plans[0]  # the first due date is a Sunday


def test_an_order_by_date_never_falls_on_a_weekend():
    supply = facts_of(tools.service_demand(DATA, "BC-02"), "service_supply")
    assert any("order by Fri 2026-10-02" in t for t in supply)  # would be Sun 2026-10-04


def test_parts_due_far_apart_go_on_separate_visits():
    plans = facts_of(tools.service_demand(DATA, "BC-01"), "service_plan")
    assert "replacing 1 x SP-1401" in plans[0] and "Left for a later visit: SP-1301" in plans[0]


def test_a_critical_part_with_long_lead_and_no_stock_gets_a_spare():
    plans = facts_of(tools.service_demand(DATA, "BC-01"), "service_plan")
    assert any("order 1 x SP-1501 today as a spare" in t for t in plans)
    assert any("order 1 x SP-1201 today as a spare" in t for t in plans)


def test_lead_time_says_when_to_order():
    plans = facts_of(tools.lead_time_question(DATA, "BC-02", "SP-1104"), "lead_time_plan")
    assert "order 4 pcs by Fri 2026-10-02" in plans[0]


def test_lead_time_for_an_overdue_part_says_overdue():
    plans = facts_of(tools.lead_time_question(DATA, "SC-01", "SP-1601"), "lead_time_plan")
    assert "overdue since" in plans[0] and "PO-4718" in plans[0]


def test_every_question_is_registered_with_whether_it_needs_a_part():
    assert tools.QUESTIONS["Service demand"][1] is False
    assert tools.QUESTIONS["Availability"][1] and tools.QUESTIONS["Lead time"][1]


def test_every_question_keeps_other_customers_confidential():
    for name, (recipe, _) in tools.QUESTIONS.items():
        brief = recipe(DATA, "BC-01", "SP-1301")
        assert "Power plant customer" in brief.confidential, name
        assert "FR-01" in brief.confidential, name
        assert "Sawmill customer" not in brief.confidential and "BC-01" not in brief.confidential, name

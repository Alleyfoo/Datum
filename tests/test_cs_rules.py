"""The service rules behind the customer-service answers, checked against the lab's own output.

golden/cs/lab_reference/ holds the lab's briefs, captured once from Parts-Service-Desk at 46c859a
(scripts/capture_lab_cs_reference.py) and never regenerated. The port must give the same text, fact
for fact, for every question on every part of every machine.

The rule tests below are the lab's own (its tests/test_desk.py), run against the port.
"""

import difflib
from datetime import timedelta
from pathlib import Path

import pytest

from cs_briefs import GOLDEN, briefs
from domains.spare_parts import tools
from domains.spare_parts.data import BomLine, Customer, Machine, Part, ServiceData, demo
from domains.spare_parts.world import AS_OF

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


# -- the rule applied and what is not known: for the receipt, never in the facts -----------


def test_the_golden_answer_names_the_competing_claim_it_does_not_weigh():
    brief = tools.availability(DATA, *GOLDEN)
    assert brief.rule == "breakdown → fastest option"
    assert brief.not_known == (
        "competing claims on PO-4718 are not modelled: SC-01 is overdue for 3 pcs, also served from FI",)
    assert not any("not modelled" in f.text for f in brief.facts)  # the facts stay the lab's


def test_a_plan_from_stock_has_no_order_claim_to_name():
    brief = tools.availability(DATA, "BC-02", "SP-1203", "breakdown")  # the transfer from SE
    assert (brief.rule, brief.not_known) == ("breakdown → fastest option", ())
    assert tools.availability(DATA, "BC-01", "SP-1301", "planned").rule == (
        "planned service → earliest option that leaves no other planned need short")


def test_claims_on_an_order_in_another_warehouse_say_where_it_arrives():
    brief = tools.availability(DATA, "SC-11", "SP-1601", "breakdown")  # a Swedish line, a Finnish order
    assert brief.not_known == (
        "competing claims on PO-4718 are not modelled: SC-01 is overdue for 3 pcs and CH-02 is due on "
        "Sun 2026-11-01 for 4 pcs, served from FI, where the order arrives",)


def test_an_order_nobody_else_is_due_for_is_still_named():
    brief = tools.lead_time_question(DATA, "BC-01", "SP-1301")
    assert brief.not_known == ("competing claims on PO-4711 are not modelled; no other planned need for "
                               "SP-1301 is served from FI within 60 days",)


def test_lead_time_and_service_demand_name_their_rule_and_the_orders_they_take():
    golden_claim = tools.availability(DATA, *GOLDEN).not_known
    lead = tools.lead_time_question(DATA, "CH-02", "SP-1601")
    assert lead.rule == "scheduled part → take free stock or an incoming order before ordering anew"
    assert lead.not_known == golden_claim
    assert tools.lead_time_question(DATA, "BC-02", "SP-1104").rule == (
        "scheduled part → order by the last working day before the due date less the lead time")
    assert tools.lead_time_question(DATA, "BC-01", "SP-1501").rule == (
        "critical part replaced on failure → a critical part with a lead time over 30 days keeps a spare")
    assert tools.lead_time_question(DATA, "BC-02", "SP-1502").rule == (
        "part replaced on failure → no order until it is needed")
    service = tools.service_demand(DATA, "CH-02")
    assert service.rule == ("service visit → bundle parts due within 30 days of the first, "
                            "on a working day when all are ready")
    assert service.not_known == golden_claim
    assert tools.service_demand(DATA, "BC-01").rule.endswith(
        "; a critical part with a lead time over 30 days keeps a spare")
    assert tools.service_demand(DATA, "BC-04").rule == "service visit → none needed within 90 days"


# -- substitute stock is checked for conflicts (backlog C13) ----------------------------


def _substitute_world() -> ServiceData:
    """Two Finnish customers. M-1 needs 2 x P-1, and no P-1 is held anywhere; the approved
    substitute P-2 has exactly 2 in FI, and M-2's planned replacement of 2 x P-2, served from FI,
    falls due in 10 days (Mon 2026-10-12)."""
    customers = {"C-1": Customer("C-1", "Customer one", "Site one", "Finland"),
                 "C-2": Customer("C-2", "Customer two", "Site two", "Finland")}
    machines = {m.machine_id: m for m in (
        Machine("M-1", "C-1", "Line one", "Belt conveyor", "Area", "A", 0, 0, 1, 1),
        Machine("M-2", "C-2", "Line two", "Belt conveyor", "Area", "B", 0, 0, 1, 1))}
    parts = {p.part_no: p for p in (
        Part("P-1", "Bearing", "Bearing", True, 7, 24, ("P-2",)),
        Part("P-2", "Bearing, alternative make", "Bearing", True, 10, 24, ("P-1",)))}
    interval = timedelta(days=round(24 * 30.4))
    bom = [BomLine("M-1", "P-1", 2, True, AS_OF - timedelta(days=100)),
           BomLine("M-2", "P-2", 2, True, AS_OF + timedelta(days=10) - interval)]
    return ServiceData(customers, machines, parts, {("P-2", "FI"): 2}, bom)


def test_planned_service_does_not_take_a_substitute_another_customer_needs():
    # the lab never weighed a substitute's stock, so its plan was the substitute, leaving M-2 short
    brief = tools.availability(_substitute_world(), "M-1", "P-1", "planned")
    [text] = facts_of(brief, "recommended_plan")
    assert text == (
        "RECOMMENDED PLAN (company rule for planned service: earliest option that leaves no other planned "
        "need short): new supplier order, arrives Fri 2026-10-09. The faster option (approved substitute P-2 "
        "from FI stock, available today (Fri 2026-10-02)) is not used because it would leave FI short for "
        "planned needs.")


def test_a_breakdown_that_takes_a_needed_substitute_restocks_the_substitute():
    brief = tools.availability(_substitute_world(), "M-1", "P-1", "breakdown")
    [text] = facts_of(brief, "recommended_plan")
    assert text == (
        "RECOMMENDED PLAN (company rule for a breakdown: fastest option): approved substitute P-2 from FI "
        "stock, available today (Fri 2026-10-02). Because this leaves FI short for planned needs, also order "
        "2 pcs of P-2 today to restock FI; with the 10-day lead time they arrive Mon 2026-10-12.")


def test_the_substitute_conflict_is_stated_as_a_fact():
    brief = tools.availability(_substitute_world(), "M-1", "P-1", "breakdown")
    assert facts_of(brief, "conflicts") == [
        "No warehouse holds a full set of 2 pcs, so no stock conflict arises.",
        "CONFLICT: taking 2 pcs of approved substitute P-2 from FI leaves 0 there, but M-2 (Customer two, "
        "2 pcs due Mon 2026-10-12) is served from FI: a shortfall of 2 pcs within 60 days.",
    ]


def test_a_substitute_nobody_else_needs_leaves_the_lab_text_unchanged():
    # no machine has SP-1311 on its parts list, so taking it starves nobody: the lab's plan stands
    brief = tools.availability(DATA, "BC-03", "SP-1301", "planned")
    assert "Option 2: approved substitute SP-1311 from FI stock, available today (Fri 2026-10-02)." in \
        facts_of(brief, "fastest_supply")
    assert not any("substitute" in text for text in facts_of(brief, "conflicts"))
    assert facts_of(brief, "recommended_plan")[0].endswith("): approved substitute SP-1311 from FI stock, "
                                                           "available today (Fri 2026-10-02).")

"""The question briefs and answer checks kept as saved text, from any module with the lab's rules.

One catalogue renders the lab's functions (scripts/capture_lab_cs_reference.py, run once) and the
port's (tests/test_cs_rules.py, tests/test_checks.py), so the lab and the port are compared case by
case with the same arguments. It imports neither: the caller passes the tools module, the data and
the check function.

A brief is kept as the expert saw it (``render()``), then the tools in the order they ran and the
names that must not reach the customer.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

#: the slice's golden case: CH-02 has stopped and needs SP-1601, on the company's date 2026-10-02
GOLDEN = ("CH-02", "SP-1601", "breakdown")

#: the consultant's reply in the golden scenario: every number and date is copied from the facts
REPLY = """\
CUSTOMER ANSWER:
We have no screw flight sections in stock. A purchase order with the full set of 4 arrives at our
Finnish warehouse on Thu 2026-10-22; we will deliver from that.

SITUATION:
- CH-02 is criticality A and has stopped; it uses 4 x SP-1601.
- Stock is 0 in FI and SE. No approved substitute.
- PO-4718 brings 4 pcs to FI on Thu 2026-10-22. A new order would arrive Mon 2026-11-16 (45 days).

RECOMMENDATION:
- Company rule for a breakdown: fastest option, so take PO-4718.
- SC-01 (another customer, FI) is overdue for 3 pcs of the same part: decide who gets PO-4718."""

#: answers checked against the golden brief: name -> answer
ANSWERS = {
    "reply": REPLY,
    # 2026-10-02 rebuilt as 2026-02-10: every piece is in the facts, the date is not (backlog C13)
    "rebuilt_date": ("CUSTOMER ANSWER:\nThe full set of 4 reaches us on 2026-02-10.\n\n"
                     "SITUATION:\n- PO-4718 is due in FI."),
    # a piece of a fact date written as a day of its own
    "date_piece": "CUSTOMER ANSWER:\nThe full set of 4 arrives on October 22.\n\nSITUATION:\n- PO-4718.",
    "invented_number": "CUSTOMER ANSWER:\nWe can send 9 pcs within 6 days.\n\nSITUATION:\n- none.",
    "other_customer": ("CUSTOMER ANSWER:\nWe take the set that the Sawmill customer was waiting for.\n\n"
                       "SITUATION:\n- SC-01 is overdue."),
    "other_machine": "CUSTOMER ANSWER:\nThe set planned for SC-01 goes to you.\n\nSITUATION:\n- none.",
    "others_named_internally": ("CUSTOMER ANSWER:\nThe full set of 4 arrives on Thu 2026-10-22.\n\n"
                                "SITUATION:\n- SC-01 (Sawmill customer) is overdue for 3 pcs."),
    "no_sections": "The full set of 4 arrives on Thu 2026-10-22; the Sawmill customer waits too.",
}


def brief_text(brief: Any) -> str:
    """A brief as the expert sees it, then the tools in order and the confidential names."""
    return "\n".join([brief.render(), "",
                      "TOOLS RUN: " + " → ".join(brief.tools_run),
                      "CONFIDENTIAL: " + ", ".join(brief.confidential)])


def briefs(tools: Any, data: Any) -> Dict[str, str]:
    """Every saved brief: file name (without .txt) -> text.

    The golden case on its own, exactly as rendered; then every question for every part on every
    machine, in the company's order.
    """
    machine_id, part_no, situation = GOLDEN
    out = {f"availability_{machine_id}_{part_no}_{situation}":
           tools.availability(data, machine_id, part_no, situation).render()}
    for situation in ("breakdown", "planned"):
        out[f"availability_{situation}"] = "\n\n".join(
            f"=== {b.machine_id} {b.part_no}\n"
            + brief_text(tools.availability(data, b.machine_id, b.part_no, situation))
            for b in data.bom)
    out["lead_time"] = "\n\n".join(
        f"=== {b.machine_id} {b.part_no}\n" + brief_text(tools.lead_time_question(data, b.machine_id, b.part_no))
        for b in data.bom)
    out["service_demand"] = "\n\n".join(
        f"=== {machine_id}\n" + brief_text(tools.service_demand(data, machine_id))
        for machine_id in data.machines)
    return out


def checks(check: Callable[[str, Any], Any], tools: Any, data: Any) -> str:
    """Each answer in ANSWERS checked against the golden brief: what the check found, one line each.

    ``check(answer, brief)`` returns an object with ``unsupported``, ``leaks`` and ``ok``.
    """
    brief = tools.availability(data, *GOLDEN)
    lines = []
    for name, answer in ANSWERS.items():
        found = check(answer, brief)
        lines.append(f"{name}: ok={found.ok!r} unsupported={tuple(found.unsupported)!r} leaks={tuple(found.leaks)!r}")
    return "\n".join(lines)

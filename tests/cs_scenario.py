"""The customer-service scenario kept as saved text: one call, tool by tool, the tickets after it, and
a call released before it is finished and resumed by a second consultant.

    "CH-02 has stopped. The customer needs SP-1601."

One catalogue renders the scenario for scripts/regen_golden_cs.py, which writes tests/golden/cs/,
and for tests/test_cs_golden.py, which compares the text in this process and in two others. It
builds a fresh record in the directory it is given, with a fixed clock, and calls the role's tools
as the consultant would. No model runs: the consultant's reply is the fixed text cs_briefs.REPLY,
and the approver's decision is a person's step in the approval queue, not a tool.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from babel.record import queue
from babel.record.consultations import STATUSES, release
from babel.record.store import Store
from cs_briefs import REPLY
from domains.spare_parts.customer_service import build
from domains.spare_parts.data import demo

#: the record's clock: fixed, so the journal is the same on every run (no tool's text shows it)
AT = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
WORKER, APPROVER = "ville", "anna"
#: the consultant who takes a released call up again
SECOND = "pia"

#: the call, in order: (tool, arguments)
CALL: List[Tuple[str, dict]] = [
    ("search", {"text": "screw"}),
    ("search", {"text": "reclaim screw"}),
    ("search", {"text": "zzz"}),
    ("open_consultation", {"customer": "C-300", "machine": "CH-02", "part": "SP-1601"}),
    ("ask", {"consultation": 1, "question": "Availability"}),
    ("stopped", {"consultation": 1, "state": "stopped"}),
    ("ask", {"consultation": 1, "question": "Availability"}),
    ("check", {"consultation": 1, "answer": REPLY}),
    ("propose_reply", {"consultation": 1, "answer": REPLY}),
]


def call_text(tool: str, arguments: dict) -> str:
    """``>>> ask(1, "Availability")``; the reply, shown once above its first use, is named ``answer``."""
    shown = ["answer" if key == "answer" else f'"{value}"' if isinstance(value, str) else repr(value)
             for key, value in arguments.items()]
    if tool == "search" and "status" in arguments:
        shown = [f'{key}="{value}"' for key, value in arguments.items()]
    return f">>> {tool}({', '.join(shown)})"


def scenario(root: Path) -> Dict[str, str]:
    """Every saved text: file name (without .txt) -> text. ``root`` must be a new, empty directory."""
    store = Store(Path(root) / "babel.sqlite", clock=lambda: AT)
    store.add_user(WORKER, ["worker"])
    store.add_user(APPROVER, ["approver"])
    store.add_user(SECOND, ["worker"])
    role = build(store, demo(), actor=WORKER)

    def run(tool: str, arguments: dict, by=role) -> str:
        return call_text(tool, arguments) + "\n" + by.call(tool, arguments)

    steps = []
    for tool, arguments in CALL:
        if tool == "check":
            steps.append("--- the consultant's reply, drafted from the FACTS (a fixed text: no model runs here)\n"
                         + REPLY)
        steps.append(run(tool, arguments))
    out = {"consultation_CH-02_SP-1601": "\n\n".join(steps)}

    # the tickets after the call: the reply approved and closed, one call released unconcluded, one at work
    reason = "Checked against the facts; PO-4718 goes to CH-02, SC-01 is followed up separately"
    queue.approve(store, 1, APPROVER, reason)
    steps = [f"--- in the approval queue, {APPROVER} (approver) approves the reply on #1: \"{reason}\""]
    steps.append(run("open_consultation", {"customer": "C-100", "machine": "SC-01", "part": "SP-1601"}))
    release(store, 3, WORKER, "the customer will call back")
    steps.append(f"--- {WORKER} releases #3 unconcluded: the customer will call back")
    steps.append(run("open_consultation", {"customer": "C-200", "machine": "SC-11"}))
    for status in STATUSES:  # every status of the filter, in its order
        steps.append(run("search", {"status": status}))
    steps.append(run("search", {"text": "zzz", "status": "open"}))
    out["tickets_by_status"] = "\n\n".join(steps)

    # a call released before it is finished, and taken up again by a second consultant: nothing is lost
    second = build(store, demo(), actor=SECOND)
    reason = "the customer is checking whether SC-11 has stopped and will call back"
    steps = [run("open_consultation", {"customer": "C-200", "machine": "SC-11", "part": "SP-1601"}),
             run("ask", {"consultation": 5, "question": "Lead time"}),
             run("ask", {"consultation": 5, "question": "Availability"}),
             run("release", {"consultation": 5, "reason": reason}),
             run("search", {"status": "open"}),
             f"--- the customer calls back, and {SECOND} takes the call",
             run("resume", {"consultation": 5}, by=second),
             run("search", {"status": "in_progress"}, by=second)]
    out["consultation_released_and_resumed"] = "\n\n".join(steps)
    return out

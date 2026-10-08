"""Text views: the plant and a machine card, drawn by code, not by a model.

Ported from Predictive-Spare-Parts-Lab desk/views.py (origin in docs/provenance.md). The text is
the lab's, checked against the lab's own output in tests/golden/views/lab_reference/.

Language models misalign columns and drop lines when they draw. So the views are
rendered here, deterministically, and a chat client shows them as they are.
They are also the menus: every machine and part has a number, so a person can
answer "3" instead of typing an id.

Symbols by default, because emoji break column alignment in terminals.

No model, no randomness, no clock: the date is the company's as-of date, ``AS_OF``.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import string
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .data import WAREHOUSES, ServiceData
from .tools import due_date
from .world import AS_OF

OK, LOW, CRITICAL, UNKNOWN = "ok", "low", "critical", "unknown"
MARK = {OK: "●", LOW: "▲", CRITICAL: "✖", UNKNOWN: "?"}
EMOJI = {OK: "🟢", LOW: "🟡", CRITICAL: "🔴", UNKNOWN: "⚪"}
LEGEND = "● covered   ▲ low   ✖ none in stock   ? no parts list"

#: weekday names as the lab printed them; fixed here so the text does not follow the locale
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _day(day: date) -> str:
    """``Fri 2026-10-02``: the lab's ``f"{day:%a} {day.isoformat()}"`` in the C locale."""
    return f"{WEEKDAYS[day.weekday()]} {day.isoformat()}"


def line_status(data: ServiceData, part_no: str, qty: int, critical: bool) -> str:
    total = sum(data.on_hand(part_no, w) for w in WAREHOUSES)
    if critical and total == 0:
        return CRITICAL
    if total < qty:
        return LOW
    return OK


def machine_status(data: ServiceData, machine_id: str) -> str:
    lines = data.bom_of(machine_id)
    if not lines:
        return UNKNOWN
    rank = {OK: 0, LOW: 1, CRITICAL: 2}
    return max((line_status(data, b.part_no, b.qty_installed, b.critical) for b in lines), key=rank.get)


def countries(data: ServiceData) -> List[str]:
    return sorted({c.country for c in data.customers.values()})


def companies(data: ServiceData, country: str) -> List[Tuple[str, str]]:
    return [(c.customer_id, c.name) for c in data.customers.values() if c.country == country]


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _issue(data: ServiceData, machine_id: str) -> str:
    none, low = [], []
    for b in data.bom_of(machine_id):
        st = line_status(data, b.part_no, b.qty_installed, b.critical)
        total = sum(data.on_hand(b.part_no, w) for w in WAREHOUSES)
        if st == CRITICAL:
            none.append(b.part_no)
        elif st == LOW:
            low.append(f"{b.part_no} ({total} of {b.qty_installed})")
    parts = []
    if none:
        parts.append("none in stock: " + ", ".join(none))
    if low:
        parts.append("low: " + ", ".join(low[:2]))
    return "; ".join(parts)


def plant_view(data: ServiceData, customer_id: str, emoji: bool = False) -> str:
    c = data.customers[customer_id]
    marks = EMOJI if emoji else MARK
    lines = [f"{c.name} · {c.site}".ljust(62) + _day(AS_OF), "",
             f"{'#':>2}  {'AREA':<13}{'MACHINE':<34}{'CRIT':<6}STATUS"]
    last_area = None
    for i, m in enumerate(data.machines_of(customer_id), 1):
        st = machine_status(data, m.machine_id)
        area = m.area if m.area != last_area else ""
        last_area = m.area
        lines.append(f"{i:>2}  {_cut(area, 12):<13}{m.machine_id + '  ' + _cut(m.name, 25):<34}"
                     f"{m.criticality:<6}{marks[st]}  {_issue(data, m.machine_id)}".rstrip())
    lines += ["", LEGEND if not emoji else "🟢 covered   🟡 low   🔴 none in stock   ⚪ no parts list"]
    return "\n".join(lines)


def machine_card(data: ServiceData, machine_id: str, emoji: bool = False) -> str:
    m = data.machines[machine_id]
    marks = EMOJI if emoji else MARK
    lines = [f"{m.machine_id} {m.name} · {m.type.lower()} · criticality {m.criticality}", "",
             f"{'#':>2}  {'PART':<9}{'DESCRIPTION':<34}{'INST':>5}{'FI':>5}{'SE':>5}  STATUS"]
    horizon = AS_OF + timedelta(days=90)
    for i, b in enumerate(data.bom_of(machine_id), 1):
        p = data.parts[b.part_no]
        st = line_status(data, b.part_no, b.qty_installed, b.critical)
        note = ""
        when = due_date(data, b)
        if when and when < AS_OF:
            note = f"overdue since {when.isoformat()}"
        elif when and when <= horizon:
            note = f"due {when.isoformat()}"
        elif st == CRITICAL:
            note = f"{p.lead_time_days} d lead"
        desc = _cut(p.description, 31) + (" ★" if b.critical else "")
        lines.append(f"{i:>2}  {b.part_no:<9}{desc:<34}{b.qty_installed:>5}"
                     f"{data.on_hand(b.part_no, 'FI'):>5}{data.on_hand(b.part_no, 'SE'):>5}  "
                     f"{marks[st]}  {note}".rstrip())
    if not data.bom_of(machine_id):
        lines.append("    no parts list recorded for this machine")
    lines += ["", "★ critical spare   " + (LEGEND if not emoji else "🟢 covered   🟡 low   🔴 none")]
    return "\n".join(lines)


MENU_QUESTIONS = {
    "B": "Availability, machine stopped",
    "P": "Availability, planned service",
    "L": "Lead time",
    "S": "Service demand (whole machine)",
}

Choices = Dict[str, Tuple[str, Optional[str]]]

# (letter, part_no, description, critical, status)
MenuPart = Tuple[str, str, str, bool, str]
# (number, machine_id, name, status, parts)
MenuMachine = Tuple[int, str, str, str, List[MenuPart]]
# (country, [(customer_id, company name, machines)])
MenuTree = List[Tuple[str, List[Tuple[str, str, List[MenuMachine]]]]]


def menu_tree(data: ServiceData) -> MenuTree:
    """The desk as data: machines numbered across the desk, parts lettered within
    a machine. The text menu and the widget are both drawn from this, so their
    codes always agree."""
    tree: MenuTree = []
    n = 0
    for country in countries(data):
        firms = []
        for cid, name in companies(data, country):
            machines: List[MenuMachine] = []
            for m in data.machines_of(cid):
                n += 1
                parts = [(letter, b.part_no, data.parts[b.part_no].description, b.critical,
                          line_status(data, b.part_no, b.qty_installed, b.critical))
                         for letter, b in zip(string.ascii_lowercase, data.bom_of(m.machine_id))]
                machines.append((n, m.machine_id, m.name, machine_status(data, m.machine_id), parts))
            firms.append((cid, name, machines))
        tree.append((country, firms))
    return tree


def desk_menu(data: ServiceData) -> Tuple[str, Choices]:
    """The whole desk as one static menu, for a chat without forms.

    Machines are numbered across the desk and parts lettered within a machine,
    so a person answers once: "1a B" (machine 1, part a, stopped) or "1 S".
    Returns the text and the codes it uses: "1" → (machine, None), "1a" → (machine, part).
    """
    lines: List[str] = []
    codes: Choices = {}
    for country, firms in menu_tree(data):
        lines += ["", country.upper()]
        for cid, name, machines in firms:
            lines.append(f"  {name} ({cid})")
            for n, machine_id, mname, st, parts in machines:
                codes[str(n)] = (machine_id, None)
                lines.append(f"  {n:>4}   {machine_id:<7}{_cut(mname, 30):<32}{MARK[st]}")
                for letter, part_no, description, critical, pst in parts:
                    codes[f"{n}{letter}"] = (machine_id, part_no)
                    desc = _cut(description, 28) + (" ★" if critical else "")
                    lines.append(f"          {letter}  {part_no:<9}{desc:<31}{MARK[pst]}")
    lines += ["", "Reply with one code:  machine number + part letter + question",
              "  B  " + MENU_QUESTIONS["B"] + "      e.g. 1a B",
              "  P  " + MENU_QUESTIONS["P"] + "      e.g. 1a P",
              "  L  " + MENU_QUESTIONS["L"] + "                          e.g. 1a L",
              "  S  " + MENU_QUESTIONS["S"] + "     e.g. 1 S  (no part letter)",
              "", "★ critical spare   " + LEGEND]
    return "\n".join(lines[1:]), codes


WIDGET = Path(__file__).with_name("desk_widget.html")


def desk_widget(data: ServiceData) -> str:
    """The same menu as clickable HTML, for a chat that renders widgets.

    Statuses are computed here, not by the model. A click produces the same code
    the text menu uses ("1a B"), so ``pick`` runs it either way.
    """
    tree = [[country, [[name, cid, [[n, mid, mname, st, [list(p) for p in parts]]
                                    for n, mid, mname, st, parts in machines]]
                       for cid, name, machines in firms]]
            for country, firms in menu_tree(data)]
    blob = json.dumps(tree, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return WIDGET.read_text(encoding="utf-8").replace("__DESK__", blob)

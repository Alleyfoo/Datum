"""The desk screens kept as saved text: a name and a text for each, from any module with the views.

One catalogue renders the lab's functions (scripts/capture_lab_reference.py, run once) and the
port's (scripts/regen_golden.py and tests/test_views_golden.py), so the lab and the port are
compared case by case with the same arguments. It imports neither: the caller passes the views
module and the data.

A view that returns text is kept as it is. Lists, tuples and dicts are written as Python
literals, one element per line where the element is itself a container, so a list cannot pass
for a tuple and a diff points at the line that changed.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict

CUSTOMERS = ("C-100", "C-200", "C-300")
MACHINES = ("BC-01", "CR-01", "BC-02", "SC-01", "BC-03", "BC-04", "BE-01", "BC-05",
            "FR-01", "SC-11", "BC-11", "BC-12", "CH-01", "CH-02", "CH-03")
COUNTRIES = ("Finland", "Sweden")

#: the emoji variant is kept for one customer only: its plant view and one of its machines
EMOJI_CUSTOMER = "C-100"
EMOJI_MACHINE = "BC-01"

#: (part_no, qty, critical): every outcome of line_status, and its edges
LINE_CASES = (
    ("SP-1001", 18, False),  # covered from one warehouse
    ("SP-1301", 4, True),    # covered only by both warehouses together
    ("SP-1203", 1, True),    # covered by the one piece in SE
    ("SP-1104", 4, False),   # some stock, fewer than installed: low
    ("SP-1601", 3, False),   # none in stock but not critical: low
    ("SP-1301", 10, True),   # critical with some stock, fewer than needed: low
    ("SP-1201", 1, True),    # critical and none anywhere: critical
    ("SP-1201", 0, False),   # nothing needed: ok with no stock
)

#: a machine the company does not have: no parts list
UNKNOWN_MACHINE = "XX-99"


def literal(value: Any, indent: int = 0) -> str:
    """A Python literal for ``value``, one element per line where elements are containers."""
    pad = "  " * indent
    if isinstance(value, dict) and value:
        body = [f"{pad}  {key!r}: {literal(item, indent + 1).lstrip()}," for key, item in value.items()]
        return "\n".join([pad + "{", *body, pad + "}"])
    if isinstance(value, (list, tuple)) and any(isinstance(v, (list, tuple, dict)) for v in value):
        start, end = ("[", "]") if isinstance(value, list) else ("(", ")")
        body = [literal(item, indent + 1) + "," for item in value]
        return "\n".join([pad + start, *body, pad + end])
    return pad + repr(value)


def service_data_text(data: Any) -> str:
    """The data the views read, field by field, one record per line."""
    lines = [type(data).__name__]
    for field in dataclasses.fields(data):
        value = getattr(data, field.name)
        lines.append(f"{field.name}:")
        if isinstance(value, dict):
            lines += [f"  {key!r}: {item!r}" for key, item in value.items()]
        else:
            lines += [f"  {item!r}" for item in value]
    return "\n".join(lines)


def screens(views: Any, data: Any) -> Dict[str, str]:
    """Every saved screen: file name (without .txt) -> text."""
    out = {"service_data": service_data_text(data)}
    out["countries"] = literal(views.countries(data))
    for country in COUNTRIES:
        out[f"companies_{country}"] = literal(views.companies(data, country))
    out["line_status"] = "\n".join(
        f"line_status({part_no!r}, {qty!r}, {critical!r}) = "
        f"{views.line_status(data, part_no, qty, critical)!r}"
        for part_no, qty, critical in LINE_CASES)
    out["machine_status"] = "\n".join(
        f"machine_status({machine_id!r}) = {views.machine_status(data, machine_id)!r}"
        for machine_id in MACHINES + (UNKNOWN_MACHINE,))
    for customer_id in CUSTOMERS:
        out[f"plant_view_{customer_id}"] = views.plant_view(data, customer_id)
    out[f"plant_view_{EMOJI_CUSTOMER}_emoji"] = views.plant_view(data, EMOJI_CUSTOMER, emoji=True)
    for machine_id in MACHINES:
        out[f"machine_card_{machine_id}"] = views.machine_card(data, machine_id)
    out[f"machine_card_{EMOJI_MACHINE}_emoji"] = views.machine_card(data, EMOJI_MACHINE, emoji=True)
    out["menu_tree"] = literal(views.menu_tree(data))
    text, codes = views.desk_menu(data)
    out["desk_menu"] = text
    out["desk_menu_codes"] = literal(codes)
    out["desk_widget"] = views.desk_widget(data)
    return out

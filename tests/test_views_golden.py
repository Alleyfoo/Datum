"""The desk's text views, checked against saved text.

golden/views/lab_reference/ holds the lab's own output, captured once from the lab at fa3836f
(scripts/capture_lab_reference.py) and never regenerated. The port must give the same text.
"""

import difflib
from pathlib import Path

import pytest

from domains.spare_parts import build
from domains.spare_parts.data import demo, from_tables
from view_screens import service_data_text

LAB = Path(__file__).parent / "golden" / "views" / "lab_reference"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _same(expected: str, actual: str, label: str) -> None:
    """Fail with a unified diff if the texts differ."""
    if actual == expected:
        return
    diff = "\n".join(difflib.unified_diff(expected.splitlines(), actual.splitlines(),
                                          f"{label} (saved)", f"{label} (port)", lineterm=""))
    if not diff:
        diff = f"the lines are equal; the ends differ: saved {expected[-20:]!r}, port {actual[-20:]!r}"
    pytest.fail(f"{label} differs from the saved text:\n{diff}", pytrace=False)


def test_the_adapter_reads_the_lab_company_from_the_tables():
    _same(_read(LAB / "service_data.txt"), service_data_text(demo()), "lab_reference/service_data.txt")


def test_the_adapter_refuses_a_warehouse_the_desk_does_not_draw():
    tables = build()
    tables["warehouse"] = tables["warehouse"] + [{"code": "NO", "name": "Norwegian warehouse", "country": "Norway"}]
    with pytest.raises(ValueError, match="warehouses"):
        from_tables(tables)

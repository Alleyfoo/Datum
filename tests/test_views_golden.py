"""The desk's text views, checked against saved text.

golden/views/lab_reference/ holds the lab's own output, captured once from the lab at fa3836f
(scripts/capture_lab_reference.py) and never regenerated. The port must give the same text.
"""

import difflib
import json
import re
from pathlib import Path

import pytest

from domains.spare_parts import build, views
from domains.spare_parts.data import demo, from_tables
from view_screens import screens, service_data_text

LAB = Path(__file__).parent / "golden" / "views" / "lab_reference"
LAB_NAMES = sorted(path.stem for path in LAB.glob("*.txt"))


@pytest.fixture(scope="module")
def port():
    """Every screen the port draws, with the arguments the lab reference was captured with."""
    return screens(views, demo())


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


def test_the_port_draws_every_screen_the_lab_was_captured_with(port):
    assert sorted(port) == LAB_NAMES


@pytest.mark.parametrize("name", LAB_NAMES)
def test_the_port_gives_the_lab_text(port, name):
    _same(_read(LAB / f"{name}.txt"), port[name], f"lab_reference/{name}.txt")


def test_the_widget_gives_every_card_the_code_of_the_text_menu():
    """Ported from the lab's tests/test_mcp.py: a click means what the typed code means."""
    data = demo()
    html = views.desk_widget(data)
    tree = json.loads(re.search(r"const D=(.*);\n", html).group(1))
    codes = {}
    for _, firms in tree:
        for _, _, machines in firms:
            for n, machine_id, _, _, parts in machines:
                codes[str(n)] = (machine_id, None)
                codes.update({f"{n}{p[0]}": (machine_id, p[1]) for p in parts})
    assert codes == views.desk_menu(data)[1]
    assert "__DESK__" not in html and "sendPrompt(c)" in html

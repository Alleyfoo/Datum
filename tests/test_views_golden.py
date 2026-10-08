"""The desk's text views, checked against saved text.

golden/views/lab_reference/ holds the lab's own output, captured once from the lab at fa3836f
(scripts/capture_lab_reference.py) and never regenerated. The port must give the same text.

golden/views/*.txt holds the port's own output, written by scripts/regen_golden.py. These tests
only read it: a missing or stale golden fails, it is never written here.
"""

import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from domains.spare_parts import build, views
from domains.spare_parts.data import demo, from_tables
from view_screens import EMOJI_CUSTOMER, screens, service_data_text

TESTS = Path(__file__).parent
ROOT = TESTS.parent
GOLDEN = TESTS / "golden" / "views"
GOLDEN_NAMES = sorted(path.stem for path in GOLDEN.glob("*.txt"))
LAB = GOLDEN / "lab_reference"
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


def test_the_goldens_are_exactly_the_screens(port):
    assert sorted(port) == GOLDEN_NAMES, "run scripts/regen_golden.py and review the diff"


def test_the_goldens_cover_every_customer_machine_and_country():
    data = demo()
    wanted = {"countries", "line_status", "machine_status", "menu_tree", "desk_menu", "desk_widget"}
    wanted |= {f"plant_view_{customer_id}" for customer_id in data.customers}
    wanted |= {f"machine_card_{machine_id}" for machine_id in data.machines}
    wanted |= {f"companies_{country}" for country in views.countries(data)}
    assert len(data.customers) == 3 and len(data.machines) == 15
    assert wanted <= set(GOLDEN_NAMES), sorted(wanted - set(GOLDEN_NAMES))


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_the_port_gives_its_golden_text(port, name):
    _same(_read(GOLDEN / f"{name}.txt"), port[name], f"{name}.txt")


CHILD = """
import json
import sys

sys.path[:0] = sys.argv[1:3]
from domains.spare_parts import views
from domains.spare_parts.data import demo
from view_screens import screens

sys.stdout.write(json.dumps(screens(views, demo()), ensure_ascii=True))
"""


def _screens_in_a_new_process(hash_seed: str) -> dict:
    """Every screen, drawn by a fresh interpreter with its own string-hash seed."""
    env = dict(os.environ, PYTHONHASHSEED=hash_seed)
    run = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), str(TESTS)],
                         capture_output=True, text=True, env=env, cwd=ROOT)
    if run.returncode:
        pytest.fail(f"the child process failed:\n{run.stderr}", pytrace=False)
    return json.loads(run.stdout)


def test_two_calls_in_one_process_give_identical_text(port):
    data = demo()
    assert screens(views, data) == screens(views, data) == port


def test_two_processes_give_identical_text(port):
    """Different hash seeds: no view may depend on the order of a set or of string hashes."""
    first, second = _screens_in_a_new_process("1"), _screens_in_a_new_process("2")
    assert first == second == port


def _emoji(text: str) -> list:
    return sorted({ch for ch in text if ch in views.EMOJI.values() or ord(ch) >= 0x1F000})


def test_emoji_are_off_by_default_and_on_for_one_customer(port):
    data = demo()
    assert all(views.plant_view(data, c) == views.plant_view(data, c, emoji=False) for c in data.customers)
    assert all(views.machine_card(data, m) == views.machine_card(data, m, emoji=False) for m in data.machines)
    assert {name: _emoji(text) for name, text in port.items()
            if not name.endswith("_emoji") and _emoji(text)} == {}

    on = views.plant_view(data, EMOJI_CUSTOMER, emoji=True)
    assert _emoji(on) == sorted(views.EMOJI.values())  # every mark is shown, in the legend at least
    marks = str.maketrans({views.EMOJI[status]: views.MARK[status] for status in views.EMOJI})
    assert on.translate(marks) == views.plant_view(data, EMOJI_CUSTOMER)  # only the marks change

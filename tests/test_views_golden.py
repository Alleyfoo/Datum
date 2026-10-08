"""The desk's text views, checked against saved text.

golden/views/lab_reference/ holds the lab's own output, captured once from the lab at fa3836f
(scripts/capture_lab_reference.py) and never regenerated. The port must give the same text.

golden/views/*.txt holds the port's own output, written by scripts/regen_golden.py. These tests
only read it: a missing or stale golden fails, it is never written here.
"""

import ast
import difflib
import json
import os
import re
import string
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from domains.spare_parts import build, tools, views
from domains.spare_parts.data import BomLine, Machine, Part, demo, from_tables
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


def test_part_letters_go_on_after_z_as_spreadsheet_columns_do():
    assert [views.part_letters(i) for i in (0, 1, 25, 26, 27, 51, 52, 701, 702)] == [
        "a", "b", "z", "aa", "ab", "az", "ba", "zz", "aaa"]
    first = [views.part_letters(i) for i in range(1000)]
    assert len(set(first)) == 1000 and all(code.isalpha() and code.islower() for code in first)


def test_a_machine_with_27_parts_keeps_every_part_in_the_menu_its_codes_and_the_widget():
    # B6: parts were lettered with zip(ascii_lowercase, ...), so the 27th dropped out without a word
    data = demo()
    extra = [Part(f"SP-9{n:03d}", f"Test part {n}", "Test", False, 7) for n in range(1, 28)]
    long_line = Machine("XX-27", "C-100", "Long test line", "Belt conveyor", "Test", "B", 0, 0, 1, 1)
    data = replace(data, machines={**data.machines, long_line.machine_id: long_line},
                   parts={**data.parts, **{p.part_no: p for p in extra}},
                   bom=data.bom + [BomLine(long_line.machine_id, p.part_no, 1, False) for p in extra])

    [(number, parts)] = [(n, parts) for _, firms in views.menu_tree(data) for _, _, machines in firms
                         for n, machine_id, _, _, parts in machines if machine_id == "XX-27"]
    assert [p[0] for p in parts] == list(string.ascii_lowercase) + ["aa"]
    assert [p[1] for p in parts] == [p.part_no for p in extra]

    text, codes = views.desk_menu(data)
    assert {code: part for code, (machine_id, part) in codes.items() if machine_id == "XX-27"} == {
        str(number): None, **{f"{number}{p[0]}": p[1] for p in parts}}
    assert (codes[f"{number}z"], codes[f"{number}aa"]) == (("XX-27", "SP-9026"), ("XX-27", "SP-9027"))
    lines = text.splitlines()
    z, aa = (next(line for line in lines if part_no in line) for part_no in ("SP-9026", "SP-9027"))
    assert (z.index("SP-9026"), z.split()[0], aa.split()[0]) == (aa.index("SP-9027"), "z", "aa")

    html = views.desk_widget(data)
    tree = json.loads(re.search(r"const D=(.*);\n", html).group(1))
    clicked = {}
    for _, firms in tree:
        for _, _, machines in firms:
            for n, machine_id, _, _, parts in machines:
                clicked[str(n)] = (machine_id, None)
                clicked.update({f"{n}{p[0]}": (machine_id, p[1]) for p in parts})
    assert clicked == codes and clicked[f"{number}aa"] == ("XX-27", "SP-9027")


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


#: all the views and the rule they read may import: text formatting, dates as values, the company
ALLOWED_IMPORTS = {
    "__future__": None, "json": None, "string": None, "typing": None,
    "datetime": {"date", "timedelta"},
    "pathlib": {"Path"},  # the widget's template, read from beside the module
    ".data": None, ".tools": None, ".world": {"AS_OF"},
}
#: a clock, chance, or a way around the import list
FORBIDDEN_NAMES = {"now", "today", "utcnow", "time", "time_ns", "monotonic", "perf_counter",
                   "random", "randint", "randrange", "choice", "shuffle", "urandom", "uuid1", "uuid4",
                   "__import__", "import_module", "eval", "exec"}


@pytest.mark.parametrize("module", [views, tools], ids=["views", "tools"])
def test_the_views_read_no_clock_randomness_or_model(module):
    """A model client, a clock or a random source needs an import outside this list, or a name in
    FORBIDDEN_NAMES. The company's own seeded history is built before the views see it."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert ALLOWED_IMPORTS.get(alias.name, ()) is None, f"import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            assert source in ALLOWED_IMPORTS, f"from {source} import ..."
            names = {alias.name for alias in node.names}
            allowed = ALLOWED_IMPORTS[source]
            assert allowed is None or names <= allowed, f"from {source} import {sorted(names - allowed)}"
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    used |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not used & FORBIDDEN_NAMES, sorted(used & FORBIDDEN_NAMES)


def test_the_date_comes_from_AS_OF(monkeypatch):
    data = demo()
    assert "due 2026-11-02" in views.machine_card(data, "BC-01")  # SP-1301, as of 2026-10-02
    monkeypatch.setattr(views, "AS_OF", date(2026, 11, 10))
    assert views.plant_view(data, "C-100").splitlines()[0].endswith("Tue 2026-11-10")
    assert "overdue since 2026-11-02" in views.machine_card(data, "BC-01")


def test_the_weekday_is_named_without_the_locale():
    monday = date(2026, 10, 5)
    assert [views._day(monday + timedelta(days=n)) for n in range(7)] == [
        "Mon 2026-10-05", "Tue 2026-10-06", "Wed 2026-10-07", "Thu 2026-10-08",
        "Fri 2026-10-09", "Sat 2026-10-10", "Sun 2026-10-11"]

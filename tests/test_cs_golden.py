"""The customer-service scenario, checked against saved text and run again for determinism.

golden/cs/*.txt holds the scenario's text (tests/cs_scenario.py: the call "CH-02 has stopped. The
customer needs SP-1601", tool by tool, the tickets after it, and a call released and resumed by a
second consultant), written by scripts/regen_golden_cs.py. These tests only read it: a missing or
stale golden fails, it is never written here. golden/cs/lab_reference/ holds the lab's own briefs,
compared in test_cs_rules.py.
"""

import difflib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from babel.record.consultations import STATUSES
from cs_scenario import scenario

TESTS = Path(__file__).parent
ROOT = TESTS.parent
GOLDEN = TESTS / "golden" / "cs"
NAMES = sorted(path.stem for path in GOLDEN.glob("*.txt"))
LAB = GOLDEN / "lab_reference"
CALL = "consultation_CH-02_SP-1601"
HANDOVER = "consultation_released_and_resumed"


@pytest.fixture(scope="module")
def texts(tmp_path_factory):
    return scenario(tmp_path_factory.mktemp("cs-scenario"))


def _flat(text: str) -> str:
    """The text with its line wrapping undone, to find a sentence a receipt wrapped."""
    return " ".join(text.split())


def _same(expected: str, actual: str, label: str) -> None:
    if actual == expected:
        return
    diff = "\n".join(difflib.unified_diff(expected.splitlines(), actual.splitlines(),
                                          f"{label} (saved)", f"{label} (run)", lineterm=""))
    pytest.fail(f"{label} differs from the saved text:\n{diff or 'the line ends differ'}", pytrace=False)


def test_the_goldens_are_exactly_the_scenarios_texts(texts):
    assert sorted(texts) == NAMES == [CALL, HANDOVER, "tickets_by_status"], \
        "run scripts/regen_golden_cs.py and review the diff"


@pytest.mark.parametrize("name", NAMES)
def test_the_scenario_gives_its_golden_text(texts, name):
    _same((GOLDEN / f"{name}.txt").read_text(encoding="utf-8"), texts[name], f"{name}.txt")


def test_the_answer_holds_the_labs_facts_line_for_line_and_its_plan(texts):
    lab = (LAB / "availability_CH-02_SP-1601_breakdown.txt").read_text(encoding="utf-8")
    answer = texts[CALL].split('>>> ask(1, "Availability")\n')[2]
    assert answer.startswith("#1 question 2: Availability of SP-1601 for CH-02\n\n" + lab + "\n\n")
    assert ("- [recommended_plan] RECOMMENDED PLAN (company rule for a breakdown: fastest option): "
            "from purchase order PO-4718, arrives Thu 2026-10-22.") in lab.splitlines()


def test_the_golden_holds_the_text_the_receipt_and_the_checks(texts):
    proposed = texts[CALL].split(">>> propose_reply(1, answer)\n")[1]
    labels = [line.split("   ")[0].strip() for line in proposed.splitlines()
              if line.startswith("  ") and not line.startswith("     ")]
    assert labels == ["asked of the person", "tools run", "rule applied", "checks", "not known", "needs approval"]
    flat = _flat(proposed)
    assert "asked of the person machine stopped: yes (breakdown), answered by ville" in flat
    assert ("tools run machine_context · stock_by_warehouse · fastest_supply · incoming_orders · lead_time · "
            "substitutes · conflicts · where_used · due_soon · recommended_plan") in flat
    assert "rule applied breakdown → fastest option" in flat
    assert "checks pass: numbers: all in the facts · dates: all in the facts, compared as whole dates" in flat
    assert "needs approval the reply waits in the approval queue on #1: a named person with the approver role" in flat
    assert "checks on #1 against question 2 (Availability of SP-1601 for CH-02): pass" in texts[CALL]


def test_the_receipt_names_the_competing_claim_that_is_not_modelled(texts):
    # criterion 2: SC-01 is overdue for 3 pcs of the same part, served from FI, and PO-4718 is not weighed for it
    claim = "not known competing claims on PO-4718 are not modelled: SC-01 is overdue for 3 pcs, also served from FI"
    for step in ('>>> ask(1, "Availability")\n#1 question 2', ">>> propose_reply(1, answer)\n"):
        assert claim in _flat(texts[CALL].split(step)[1].split(">>> ")[0]), step


def test_the_status_filter_after_the_call(texts):
    after = texts["tickets_by_status"]
    assert 'search status open: 1 ticket, shown; viewing it changes nothing.\n\n#3 consultation · open' in after
    assert '#4 consultation · in_progress, with ville' in after
    assert 'search "zzz" with status open: no ticket.' in after
    # every status of the filter is searched once, and the approved call is listed by exactly one of them,
    # the status its approval ended it in, as its card with the approver's decision
    searches = [step for step in after.split("\n\n>>> ") if step.startswith("search(status=")]
    assert [step.split("\n")[0] for step in searches] == [f'search(status="{s}")' for s in STATUSES]
    [listed] = [step for step in searches if "\n#1 consultation · " in step]
    assert "\nReply: approved by anna (decision #2): Checked against the facts; PO-4718 goes to CH-02" in listed


def test_the_released_call_is_resumed_by_a_second_consultant_as_it_was_left(texts):
    # P26 (build-plan section 25): released with its reason, listed under open, resumed with nothing lost
    steps = {step.split("\n")[0]: step for step in texts[HANDOVER].split("\n\n>>> ")}
    released = steps['release(5, "the customer is checking whether SC-11 has stopped and will call back")']
    resumed = steps["resume(5)"]
    reason = "  released   by ville: the customer is checking whether SC-11 has stopped and will call back"
    assert released.split("\n")[1] == ("Consultation #5 released: open, with no one. Nothing was decided, "
                                       "and nothing is deleted.")
    assert resumed.split("\n")[1] == "Consultation #5 resumed: in_progress, with pia, as it was left."
    for step in (released, resumed):  # the same questions and answers, before and after
        assert reason in step
        assert "   1  Lead time of SP-1601 for SC-11  ·  answered: " in step
        assert "Open questions, of all 2: 2 (Has SC-11 stopped?)" in step
    assert "  resumed    by pia" in resumed and "  resumed" not in released
    assert " 2  #5    consultation  Consultation: Power plant customer · SC-11 Fuel screen screw · SP-1601 Screw " \
           "flight section, 400 mm  ·  open" in steps['search(status="open")']
    assert steps['search(status="in_progress")'].endswith("·  in_progress, with pia")


def test_two_runs_in_one_process_give_identical_text(texts, tmp_path):
    assert scenario(tmp_path / "first") == scenario(tmp_path / "second") == texts


CHILD = """
import json
import sys
import tempfile
from pathlib import Path

sys.path[:0] = sys.argv[1:3]
from cs_scenario import scenario

with tempfile.TemporaryDirectory() as tmp:
    texts = scenario(Path(tmp))
sys.stdout.write(json.dumps(texts, ensure_ascii=True))
"""


def _in_a_new_process(hash_seed: str) -> dict:
    """The scenario, run by a fresh interpreter with its own string-hash seed, on its own record."""
    env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONDONTWRITEBYTECODE="1")
    run = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), str(TESTS)],
                         capture_output=True, text=True, env=env, cwd=ROOT)
    if run.returncode:
        pytest.fail(f"the child process failed:\n{run.stderr}", pytrace=False)
    return json.loads(run.stdout)


def test_two_processes_give_identical_text(texts):
    """Different hash seeds: no text may depend on the order of a set or on string hashes."""
    first, second = _in_a_new_process("1"), _in_a_new_process("2")
    assert first == second == texts

"""The synthetic demo run (scripts/demo_run.py): one scenario end to end, written as plain files.

The run is made once for the module and read back; the determinism test runs it twice more, once in
another process with another hash seed, and compares the bytes of demo.json and demo.md.
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from datum.record.store import RecordError, Store

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_run.py"
WRITTEN = ("demo.json", "demo.md")


def _script():
    spec = importlib.util.spec_from_file_location("demo_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_run = _script()


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    folder = tmp_path_factory.mktemp("demo") / "out"
    assert demo_run.main(["--out", str(folder)]) == 0
    return folder


@pytest.fixture(scope="module")
def run(out):
    return json.loads((out / "demo.json").read_text(encoding="utf-8"))


def _step(run, key):
    return next(step for step in run["steps"] if step["id"] == key)


def _moves(step):
    return [(c["by"], c["action"], c["from"], c["to"]) for c in step["status_changes"]]


def _bytes(folder):
    return {name: (folder / name).read_bytes() for name in WRITTEN}


def test_two_runs_with_the_same_arguments_write_byte_identical_demo_files(tmp_path):
    folder = tmp_path / "demo"
    assert demo_run.main(["--out", str(folder)]) == 0
    first = _bytes(folder)
    # the same arguments again, in another process with another hash seed: the earlier output is replaced
    again = subprocess.run([sys.executable, str(SCRIPT), "--out", str(folder)], cwd=ROOT, capture_output=True,
                           text=True, env={**os.environ, "PYTHONHASHSEED": "12345"})
    assert again.returncode == 0, again.stderr
    assert _bytes(folder) == first
    # and in another directory: no path outside DIR is written
    assert demo_run.main(["--out", str(tmp_path / "elsewhere" / "demo")]) == 0
    assert _bytes(tmp_path / "elsewhere" / "demo") == first


def test_dir_holds_the_record_the_company_folder_the_arrivals_and_the_demo_files(out, run):
    assert sorted(p.name for p in out.iterdir()) == ["arrivals", "data", "demo.json", "demo.md", "record.sqlite"]
    assert run["written_by"] == "scripts/demo_run.py"
    assert run["files"] == {"store": "record.sqlite", "data": "data", "arrivals": "arrivals",
                            "demo": ["demo.json", "demo.md"]}
    assert [s["id"] for s in run["steps"]] == ["setup", "a", "b", "c", "d"]
    assert sorted(p.name for p in (out / "arrivals").iterdir()) == [
        "stock_export_2026-08-14.xlsx", "stock_export_2026-08-21.xlsx", "stock_export_2026-08-28.xlsx"]
    ledger = (out / "data" / "customers" / "spare-parts" / "inbox" / "ledger.jsonl").read_text(encoding="utf-8")
    assert [json.loads(line)["original_name"] for line in ledger.splitlines()] == sorted(
        p.name for p in (out / "arrivals").iterdir())


def test_the_weekly_export_fits_version_1_and_an_approver_admits_it(run):
    setup, weekly = _step(run, "setup"), _step(run, "a")
    assert setup["outcome"] == "no_schema"  # the company had no schema yet: version 1 is drafted from this file
    assert [c["call"] for c in setup["calls"]] == ["hook.trigger", "store.open_ticket", "schemas.draft",
                                                   "schemas.confirm", "dispositions.admit"]
    assert weekly["outcome"] == "fits"
    assert weekly["ticket"]["status"] == "finished"
    assert _moves(weekly) == [("hook", "created", None, "open"), ("hook", "proposed", "open", "needs_input"),
                              ("anna", "approved", "needs_input", "finished")]
    assert "Trial against schema stock_export v1: fits: 19 rows, 0 refusals" in weekly["receipt"]
    assert "Verified: every sheet rebuilt from the raw file gives its staged fingerprint" in weekly["receipt"]
    assert "is accepted as stock_export version 1 for spare-parts." in weekly["receipt"]


def test_the_renamed_column_is_refused_with_a_verified_reason_and_loads_under_the_amendment(run):
    renamed = _step(run, "b")
    assert renamed["outcome"] == "structural_change"
    assert renamed["refused_with"] == ("Trial against schema stock_export v1: structural change: 1 difference(s) in "
                                       "sheet, header row or headers")
    assert "c004: expected 'On hand', found 'Quantity on hand' (type code s)" in renamed["receipt"]
    assert "Gate passed: the full rule list is on the ticket" in renamed["receipt"]
    assert "is accepted as stock_export version 2 for spare-parts." in renamed["receipt"]
    assert _moves(renamed) == [("hook", "created", None, "open"), ("ville", "opened", "open", "in_progress"),
                               ("ville", "proposed", "in_progress", "needs_input"),
                               ("anna", "approved", "needs_input", "finished")]
    versions = run["after"]["schema_versions"]
    assert [(v["version"], v["status"], v["headers"][3], v["drafted_by"], v["decided_by"]) for v in versions] == [
        (1, "superseded", "On hand", "ville", "anna"), (2, "active", "Quantity on hand", "ville", "anna")]
    assert [(f["ticket"], f["schema_version"]) for f in run["after"]["accepted_files"]] == [
        (_step(run, "setup")["ticket"]["number"], 1), (_step(run, "a")["ticket"]["number"], 1),
        (renamed["ticket"]["number"], 2)]  # the files accepted under version 1 keep it


def test_the_call_is_answered_with_its_receipt_and_the_approvers_approval_finishes_it(run):
    call = _step(run, "c")
    assert [c["call"] for c in call["calls"]] == ["search", "open_consultation", "ask", "stopped", "ask", "check",
                                                  "propose_reply", "queue.approve", "search"]
    assert all(c["kind"] == "tool" for c in call["calls"] if c["call"] != "queue.approve")
    asked, answered = (c["result"] for c in call["calls"] if c["call"] == "ask")
    assert "waits for the person. No answer is given without it." in asked  # never guessed
    assert "RECOMMENDED PLAN (company rule for a breakdown: fastest option): from purchase order PO-4718" in answered
    assert call["calls"][5]["result"].splitlines()[0].endswith(": pass")
    number = call["ticket"]["number"]
    approved = call["calls"][7]["result"]
    assert approved.splitlines()[1] == ("Approved by anna (approver): Checked against the facts: PO-4718 goes to "
                                        "CH-02, and SC-01 is followed up separately")
    decision = approved.split(" ", 1)[0]  # "#15": the approval is a decision document about the consultation
    for line in (f"RECEIPT  #{number} question 2: Availability of SP-1601 for CH-02",
                 "asked of the person   machine stopped: yes (breakdown), answered by ville",
                 "rule applied          breakdown → fastest option",
                 "not known             competing claims on PO-4718 are not modelled",
                 f"needs approval        decided: see decision {decision} about #{number}"):
        assert line in call["receipt"], line
    assert _moves(call) == [("ville", "created", None, "open"), ("ville", "opened", "open", "in_progress"),
                            ("ville", "proposed", "in_progress", "needs_input"),
                            ("anna", "approved", "needs_input", "finished")]
    assert call["ticket"]["status"] == "finished"


def test_a_closed_call_shows_its_notice_and_the_sweep_31_days_later_deletes_it_and_keeps_the_finished(out, run):
    closing = _step(run, "d")
    gone = closing["ticket"]["number"]
    closed = next(c["result"] for c in closing["calls"] if c["call"] == "close")
    assert f"Notice to ville: #{gone} is closed: it could not be finished." in closed
    assert date.fromisoformat(closing["sweep"]["on"]) - date.fromisoformat(closing["date"]) == timedelta(days=31)
    assert closing["calls"][-1]["result"] == f"sweep {closing['sweep']['on']}: deleted #{gone}"
    assert _moves(closing)[-2:] == [("ville", "closed", "in_progress", "closed"), ("system", "deleted", "closed", None)]
    finished = [_step(run, key)["ticket"]["number"] for key in ("setup", "a", "b", "c")]
    assert closing["sweep"]["deleted"] == [gone] and closing["sweep"]["kept_finished"] == finished
    assert [(t["number"], t["status"]) for t in run["after"]["tickets"]] == [(n, "finished") for n in finished]
    assert [d["ticket"] for d in run["after"]["deleted"]] == [gone]
    assert run["after"]["approval_queue"] == []
    store = Store(out / "record.sqlite")  # the record agrees: the closed ticket and its journal are gone
    with pytest.raises(RecordError) as missing:
        store.get(gone)
    assert missing.value.code == "unknown_item" and store.journal(gone) == []
    assert all(store.get(n)["status"] == "finished" and store.journal(n) for n in finished)


def test_demo_md_tells_each_step_with_its_calls_and_its_receipt(out, run):
    text = (out / "demo.md").read_text(encoding="utf-8")
    for step in run["steps"]:
        head = "## Setup: " if step["id"] == "setup" else f"## Step {step['id']}: "
        assert head + step["title"] in text
        assert step["receipt"] in text
        assert all(c["result"] in text for c in step["calls"])
    assert "`python -m datum.record.sweep --store record.sqlite --today 2026-11-02`" in text


def test_a_directory_with_files_this_script_did_not_write_is_refused_and_left_as_it_is(tmp_path, capsys):
    notes, data = tmp_path / "notes", tmp_path / "data"
    notes.mkdir()
    (notes / "notes.txt").write_text("someone's notes", encoding="utf-8")
    (data / "data").mkdir(parents=True)  # named like an output of this script, but with no demo.json beside it
    for folder, kept in ((notes, "notes.txt"), (data, "data")):
        with pytest.raises(SystemExit) as refused:
            demo_run.main(["--out", str(folder)])
        assert refused.value.code == 2
        assert "holds files this script did not write" in capsys.readouterr().err
        assert [p.name for p in folder.iterdir()] == [kept]
    assert (notes / "notes.txt").read_text(encoding="utf-8") == "someone's notes"


def test_an_interrupted_run_is_replaced(tmp_path):
    folder = tmp_path / "demo"
    demo_run.fresh(folder)  # the marker a run writes first
    inbox = folder / "data" / "customers" / "spare-parts" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "ledger.jsonl").write_text("")
    os.chmod(inbox / "ledger.jsonl", 0o444)  # the inbox keeps its files read-only
    assert demo_run.main(["--out", str(folder)]) == 0
    assert json.loads((folder / "demo.json").read_text(encoding="utf-8"))["steps"]


#: what the demo may not reach: a model, the network, another process, a timer or chance
FORBIDDEN = {"urllib", "http", "socket", "ssl", "requests", "httpx", "subprocess", "multiprocessing", "sched",
             "threading", "asyncio", "time", "random", "secrets", "uuid", "anthropic", "openai", "ollama", "mcp"}


def test_the_demo_reaches_no_model_no_network_no_timer_and_no_chance():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert not imported & FORBIDDEN

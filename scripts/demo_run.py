"""One synthetic demo run, end to end, with fixed dates and no model: the files a static demo page reads.

    python scripts/demo_run.py --out DIR

It builds a fresh record in DIR from the synthetic spare-parts company and runs one scenario, step
by step, as the people and the intake hook would:

  setup  the company's stock-export schema, version 1. The export of the week ending 2026-08-14
         arrives before the company has a schema; a worker drafts version 1 from it, an approver
         confirms it at the create-schema gate and admits the file.
  a      the weekly stock export (C25) of the week ending 2026-08-21 arrives and passes the trial
         against version 1; an approver admits it.
  b      the export of the week ending 2026-08-28 arrives with "On hand" renamed "Quantity on hand"
         (C25's renamed-column variant) and is refused with a verified reason; a worker drafts the
         amendment, version 2, an approver confirms it, and the file loads under version 2.
  c      the customer-service consultation: CH-02 has stopped and needs SP-1601. The consultant's
         tools, the person's answer (stopped), the answer with its receipt, the checks, and the
         reply proposed for an approver, whose approval finishes the consultation.
  d      a call that cannot be finished, closed by the worker with the reason (its card shows the
         notice to the person who answers for it), and the daily sweep, run once 31 days later: it
         deletes that closed ticket and keeps the finished ones.

Nothing runs on a timer: each step is a call made on the date the scenario gives it, and the
record's clock is set to that date. No model runs: the consultant's reply is the golden scenario's
fixed text (tests/cs_briefs.py), and every other text is what the tools and the record return. The
consultant's tools are called as an MCP client calls them, by name with JSON arguments, through the
role's registry, which is what the MCP server passes each call to.

DIR then holds plain files:

  demo.json      each step with its ticket, the ticket's status changes, the calls made and what came
                 back, the documents written and the receipt; then the record as the run leaves it
  demo.md        the same, to read
  record.sqlite  the ticket store
  data/          the company's folder: the inbox (each arrived file, read-only, and its ledger),
                 staging and the cleaning records
  arrivals/      the synthetic exports as they arrived, before the hook preserved them

In demo.json each call is recorded as {at, by, kind, call, arguments, result}, the replay format of
build-plan G11: kind "tool" is a role tool called as an MCP client calls it, "step" a person's or the
hook's step at the record, and "command" a command an operator runs. A status change is {at, by,
role, action, from, to, reason}, read from the ticket's journal.

Two runs with the same arguments write byte-identical demo.json and demo.md: they hold no clock
time but the scenario's, no random number and no path outside DIR. The record itself is not
byte-identical: the inbox ledger and manifests keep the time each file was preserved, by the
machine's clock. DIR must be new, empty, or an earlier output of this script (an interrupted one
too), which is replaced; anything else is refused, and nothing in it is touched. The output is
never committed: write it outside the repository, or under output/, which git ignores.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import stat
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]  # the golden reply is kept with the tests

from datum.intake import accepted, dispositions, hook, schemas, staging  # noqa: E402
from datum.mcp import Registry  # noqa: E402
from datum.record import consultations, queue, sweep  # noqa: E402
from datum.record.store import CLOSED_RETENTION_DAYS, Store  # noqa: E402
from cs_briefs import REPLY  # noqa: E402
from domains.spare_parts.customer_service import build as customer_service  # noqa: E402
from domains.spare_parts.data import demo  # noqa: E402
from domains.spare_parts.exports import RENAMED_FROM, RENAMED_TO, stock_export  # noqa: E402
from domains.spare_parts.world import AS_OF, SEED  # noqa: E402

WRITTEN_BY = "scripts/demo_run.py"
#: the synthetic spare-parts company itself, whose ERP sends the weekly stock export of its warehouses;
#: not one of its customers (C-100 to C-300), who appear in the consultation
COMPANY = "spare-parts"
FILE_KIND = "stock_export"
APPROVER, WORKER = "anna", "ville"
STORE, DATA, ARRIVALS, JSON_FILE, MD_FILE = "record.sqlite", "data", "arrivals", "demo.json", "demo.md"
#: what this script writes in DIR, and so all it may replace there
OWN = (STORE, f"{STORE}-wal", f"{STORE}-shm", DATA, ARRIVALS, JSON_FILE, MD_FILE)


def _utc(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)


#: when each step starts: a weekly export arrives on the Monday after its week, and the calls come on the
#: desk's own date (AS_OF), so the consultation's facts and the record's clock agree
SETUP_AT, A_AT, B_AT = _utc(date(2026, 8, 17), 9), _utc(date(2026, 8, 24), 9), _utc(date(2026, 8, 31), 9)
C_AT, D_AT = _utc(AS_OF, 10), _utc(AS_OF, 14)
#: the sweep's date: 31 days after the close, one day past the closed ticket's retention
SWEEP_ON = D_AT.date() + timedelta(days=CLOSED_RETENTION_DAYS + 1)


class DemoError(ValueError):
    """The run was refused before anything was written: the text says why."""


class Clock:
    """The record's clock: set to each step's moment, and moved on a few minutes after each action."""

    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def set(self, at: datetime) -> None:
        if at < self.at:
            raise ValueError(f"the scenario's clock only goes forward: {at} is before {self.at}")
        self.at = at

    def tick(self, minutes: int = 3) -> None:
        self.at += timedelta(minutes=minutes)


# -- the output directory --------------------------------------------------------------------------

def _is_output(folder: Path) -> bool:
    try:
        return json.loads((folder / JSON_FILE).read_text(encoding="utf-8")).get("written_by") == WRITTEN_BY
    except (OSError, ValueError, AttributeError):
        return False


def _remove(path: Path) -> None:
    """Remove one of this script's outputs. The inbox keeps its files read-only: make them writable first."""
    if path.is_dir() and not path.is_symlink():
        for inner in path.rglob("*"):
            if inner.is_file() and not inner.is_symlink():
                os.chmod(inner, stat.S_IREAD | stat.S_IWRITE)
        shutil.rmtree(path)
    else:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        path.unlink()


def fresh(out: Path) -> None:
    """Make DIR ready for a run: new, empty, or this script's earlier output, which is removed. A
    marker demo.json is written first, so an interrupted run's output is recognised and replaced."""
    if out.exists() and not out.is_dir():
        raise DemoError(f"{out} is not a directory")
    found = sorted(p.name for p in out.iterdir()) if out.exists() else []
    if found:
        others = [name for name in found if name not in OWN]
        if others or not _is_output(out):
            raise DemoError(f"{out} holds files this script did not write ({', '.join(others or found)}): "
                            "give a new or empty directory, or an earlier output of this script")
        for name in found:
            _remove(out / name)
    out.mkdir(parents=True, exist_ok=True)
    (out / JSON_FILE).write_text(json.dumps({"written_by": WRITTEN_BY, "complete": False}) + "\n",
                                 encoding="utf-8", newline="\n")


# -- reading the record ------------------------------------------------------------------------------

def ticket(store: Store, number: int) -> dict:
    item = store.get(number)
    return {"number": number, "type": item["type"], "title": item["title"], "status": item["status"],
            "created_by": item["created_by"], "recipient": item["recipient"]}


def status_changes(store: Store, number: int) -> List[dict]:
    """A ticket's status, from its journal: created open, then each entry that changed it."""
    out = []
    for entry in store.journal(number):
        status = entry["details"].get("status")
        if entry["action"] == "created":
            before, after = None, "open"
        elif isinstance(status, dict):
            before, after = status["before"], status["after"]
        else:
            continue
        change = {"at": entry["at"], "by": entry["actor"], "role": entry["role"], "action": entry["action"],
                  "from": before, "to": after}
        if entry["details"].get("reason"):
            change["reason"] = entry["details"]["reason"]
        out.append(change)
    return out


def documents(store: Store, after: int) -> List[dict]:
    """The findings and decisions with a number above `after`, in number order."""
    return [{"number": d["number"], "type": d["type"], "title": d["title"], "body": d["body"]}
            for d in store.items("document") if d["number"] > after]


def documents_text(written: List[dict]) -> str:
    """Documents as the ticket keeps them: number, kind and title, then the text."""
    return "\n\n".join(f"#{d['number']} {d['type']}: {d['title']}\n{d['body']}" for d in written)


def audit_lines(store: Store) -> List[dict]:
    """What the record keeps of a deleted ticket: its audit line, a journal entry on no item."""
    return [{"ticket": e["details"]["ticket"], "closed_at": e["details"]["closed_at"],
             "deleted_at": e["details"]["deleted_at"], "by": e["actor"], "role": e["role"]}
            for e in store.journal() if e["action"] == "deleted" and e["item"] is None]


# -- the run -------------------------------------------------------------------------------------------

class Run:
    """One scenario on a fresh record, kept step by step for demo.json and demo.md."""

    def __init__(self, out: Path):
        self.out = out
        self.clock = Clock(SETUP_AT)
        self.store = Store(out / STORE, clock=self.clock)
        self.root = out / DATA
        (self.root / "customers" / COMPANY).mkdir(parents=True)
        (out / ARRIVALS).mkdir()
        self.store.add_user(APPROVER, ["approver"])
        self.store.add_user(WORKER, ["worker"])
        self.roles: Dict[str, Registry] = {}
        self.steps: List[dict] = []
        self.step: dict = {}
        self.since = 0  # the last item number before the step began

    def begin(self, key: str, title: str, at: datetime, story: str) -> None:
        self.clock.set(at)
        self.since = max((item["number"] for item in self.store.items()), default=0)
        self.step = {"id": key, "title": title, "date": at.date().isoformat(), "story": story, "calls": []}

    def called(self, by: str, kind: str, call: str, arguments: dict, result: str, at: Optional[str] = None) -> None:
        self.step["calls"].append({"at": at or self.store.now(), "by": by, "kind": kind, "call": call,
                                   "arguments": arguments, "result": result})

    def end(self, number: int, *, receipt: Optional[str] = None, summary: Optional[dict] = None,
            changes: Optional[List[dict]] = None, **more) -> None:
        """Close the step on its ticket: the ticket now, its status changes, the documents written, and the
        receipt, by default those documents as the ticket keeps them. A ticket the step deleted is given as
        it was read before (`summary`, `changes`): the record keeps only its audit line."""
        written = documents(self.store, self.since)
        self.step.update(ticket=summary or ticket(self.store, number),
                         status_changes=status_changes(self.store, number) if changes is None else changes,
                         documents=written, receipt=documents_text(written) if receipt is None else receipt)
        self.step.update(more)
        self.steps.append(self.step)

    def newest(self) -> int:
        return self.store.items("task")[-1]["number"]

    # the hook and the people at the record

    def arrive(self, week_ending: date, *, renamed: bool = False) -> hook.Arrival:
        name = f"stock_export_{week_ending.isoformat()}.xlsx"
        path = stock_export(self.out / ARRIVALS / name, seed=SEED, week_ending=week_ending, renamed=renamed)
        arrival = hook.trigger(self.root, COMPANY, path, store=self.store)
        self.called(hook.HOOK, "step", "hook.trigger", {"company": COMPANY, "file": f"{ARRIVALS}/{name}"},
                    f"#{arrival.ticket} {self.store.get(arrival.ticket)['title']}")
        self.clock.tick()
        return arrival

    def open(self, number: int, by: str) -> None:
        item = self.store.open_ticket(number, by)
        self.called(by, "step", "store.open_ticket", {"ticket": number},
                    f"#{number} is {item['status']}, with {item['claimed_by']}")
        self.clock.tick()

    def draft(self, arrival: hook.Arrival, by: str, reason: str) -> None:
        [sheet] = staging.datasets(self.root, COMPANY, arrival.source_id)
        schema, _ = schemas.suggest(sheet)  # read off the staged sheet: what the worker checks and drafts
        versioned = schemas.draft(self.store, arrival.ticket, by, FILE_KIND, schema, reason)
        self.called(by, "step", "schemas.draft",
                    {"ticket": arrival.ticket, "file_kind": FILE_KIND, "headers": list(schema.names), "reason": reason},
                    f"{FILE_KIND} version {versioned.version} drafted from {arrival.source_id} and proposed to an "
                    f"approver. Its rules, listed on the ticket:\n{schema.rule_text()}")
        self.clock.tick()

    def decided(self, call: str, number: int, reason: str) -> None:
        """An approver's decision: a decision document about the ticket, whose text is what came back."""
        decision = self.store.get(self.store.get(number)["data"]["decisions"][-1])
        self.called(APPROVER, "step", call, {"ticket": number, "reason": reason},
                    f"#{decision['number']} {decision['title']}\n{decision['body']}")
        self.clock.tick()

    def confirm(self, number: int, reason: str) -> None:
        schemas.confirm(self.store, self.root, number, APPROVER, reason)
        self.decided("schemas.confirm", number, reason)

    def admit(self, number: int, reason: str) -> None:
        dispositions.admit(self.store, number, APPROVER, reason)
        self.decided("dispositions.admit", number, reason)

    def approve(self, number: int, reason: str) -> None:
        queue.approve(self.store, number, APPROVER, reason)
        self.decided("queue.approve", number, reason)

    def tool(self, name: str, arguments: dict, by: str = WORKER) -> str:
        """A customer-service tool, as an MCP client calls it: by name, with JSON arguments; text comes back."""
        if by not in self.roles:
            self.roles[by] = customer_service(self.store, demo(), actor=by)
        text = self.roles[by].call(name, arguments)
        self.called(by, "tool", name, arguments, text)
        self.clock.tick(2)
        return text

    def run_sweep(self, on: date) -> str:
        """The daily sweep, as an operator's scheduler would run it: the command, once, on the date it is given."""
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = sweep.main(["--store", str(self.out / STORE), "--today", on.isoformat()])
        if code != 0:
            raise RuntimeError(f"the sweep failed with exit code {code}")
        said = printed.getvalue().strip()
        self.called("system", "command", "python -m datum.record.sweep", {"store": STORE, "today": on.isoformat()},
                    said, at=_utc(on, 0).isoformat())
        return said


def scenario(out: Path) -> dict:
    """Run the scenario on a fresh record in `out`; return what demo.json holds."""
    run = Run(out)
    store = run.store

    run.begin("setup", "The company's stock-export schema, version 1", SETUP_AT,
              "The first weekly stock export arrives before the company has a schema for it, so it is not tried. "
              "A worker opens its ticket and drafts version 1 from the file; an approver confirms it at the "
              "create-schema gate, where the file must pass its own draft with zero refusals, and admits the file.")
    first = run.arrive(date(2026, 8, 14))
    run.open(first.ticket, WORKER)
    run.draft(first, WORKER, "Drafted from the ERP's weekly stock export: five headers, every value filled")
    run.confirm(first.ticket, "These are the ERP stock export's headers and types")
    run.admit(first.ticket, "The first export, zero refusals")
    run.end(first.ticket, outcome=first.outcome)

    run.begin("a", "The weekly stock export arrives, fits and is admitted", A_AT,
              "This week's export (C25) arrives. The hook preserves it, stages it, cleans it and tries it against "
              "version 1: it fits with zero refusals, and the hook proposes the import. An approver admits it.")
    weekly = run.arrive(date(2026, 8, 21))
    run.admit(weekly.ticket, "This week's export, zero refusals")
    run.end(weekly.ticket, outcome=weekly.outcome)

    run.begin("b", "A renamed column is refused, the schema is amended, and the file loads", B_AT,
              f'The next export arrives with "{RENAMED_FROM}" renamed "{RENAMED_TO}", after an update of the ERP. '
              "The trial against version 1 refuses it as a structural change, and the reason is verified against "
              "the raw file before the ticket states it. A worker drafts the amendment, version 2; an approver "
              "confirms it, and the file loads under version 2. The files accepted under version 1 keep it.")
    renamed = run.arrive(date(2026, 8, 28), renamed=True)
    [refusal] = documents(store, run.since)
    run.open(renamed.ticket, WORKER)
    run.draft(renamed, WORKER, f'The ERP renamed "{RENAMED_FROM}" to "{RENAMED_TO}"; it is the same column')
    run.confirm(renamed.ticket, "The same column under the ERP's new name")
    run.admit(renamed.ticket, "Loads under version 2 with zero refusals")
    run.end(renamed.ticket, outcome=renamed.outcome, refused_with=refusal["title"])

    run.begin("c", "A customer call: CH-02 has stopped and needs SP-1601", C_AT,
              '"CH-02 has stopped. The customer needs SP-1601." The consultant searches, opens the call\'s ticket '
              "and asks for availability; the tools ask the person whether the machine has stopped instead of "
              "guessing it. With the answer recorded, the rules give the facts and the receipt. The consultant's "
              "reply (a fixed text: no model runs) passes the checks and is proposed. An approver approves it in "
              "the approval queue, which finishes the consultation. Nothing is sent from the record.")
    run.tool("search", {"text": "CH-02"})
    run.tool("open_consultation", {"customer": "C-300", "machine": "CH-02", "part": "SP-1601"})
    call = run.newest()
    run.tool("ask", {"consultation": call, "question": "Availability"})
    run.tool("stopped", {"consultation": call, "state": "stopped"})
    run.tool("ask", {"consultation": call, "question": "Availability"})
    run.tool("check", {"consultation": call, "answer": REPLY})
    run.tool("propose_reply", {"consultation": call, "answer": REPLY})
    run.approve(call, "Checked against the facts: PO-4718 goes to CH-02, and SC-01 is followed up separately")
    run.tool("search", {"status": "finished"})
    item = consultations.get(store, call)
    run.end(call, receipt=consultations.receipt_text(item, consultations.latest_answer(item)), reply=REPLY)

    run.begin("d", "A call that cannot be finished is closed, and the sweep deletes it 31 days later", D_AT,
              "Another call cannot be finished: the customer withdraws it. The worker closes its ticket with the "
              "reason, and the ticket tells the person who answers for it that they may amend it and repost it, or "
              f"delete it. Nobody reacts. The daily sweep, run once on {SWEEP_ON.isoformat()}, 31 days later, deletes "
              "the closed ticket with its history and keeps one audit line; the finished tickets stay, with theirs.")
    run.tool("open_consultation", {"customer": "C-200", "machine": "SC-11"})
    gone = run.newest()
    closed = run.tool("close", {"consultation": gone, "reason": (
        "The customer withdrew the call: their own maintenance found a spare screw in their store")})
    before = ticket(store, gone)
    changes = status_changes(store, gone)  # read now: the sweep takes the ticket's journal with it
    said = run.run_sweep(SWEEP_ON)
    [audit] = [line for line in audit_lines(store) if line["ticket"] == gone]
    finished = [t["number"] for t in store.items("task") if t["status"] == "finished"]
    receipt = "\n".join([line for line in closed.splitlines() if line.startswith(("Closed by ", "Notice to "))]
                        + ["", said, f"audit line: #{gone} closed {audit['closed_at']}, deleted {audit['deleted_at']} "
                                     f"by {audit['by']}; nothing else of it is kept",
                           "kept, finished: " + ", ".join(f"#{n}" for n in finished)])
    run.end(gone, receipt=receipt, summary={**before, "status": "deleted"},
            changes=changes + [{"at": audit["deleted_at"], "by": audit["by"], "role": audit["role"],
                                "action": "deleted", "from": "closed", "to": None}],
            sweep={"on": SWEEP_ON.isoformat(), "deleted": [gone], "kept_finished": finished})

    return {
        "written_by": WRITTEN_BY,
        "title": "Datum: one synthetic run",
        "about": ("One scenario on a fresh record, with fixed dates and no model: a weekly stock export admitted, "
                  "a renamed column refused and the schema amended, a customer call answered with its receipt and "
                  "approved, and a call closed and deleted by the sweep 31 days later. Synthetic data only."),
        "company": {"id": COMPANY, "seed": SEED, "as_of": AS_OF.isoformat()},
        "people": [{"name": u["name"], "kind": u["kind"], "roles": list(u["roles"])}
                   for u in (store.user(name) for name in (APPROVER, WORKER, hook.HOOK))],
        "files": {"store": STORE, "data": DATA, "arrivals": ARRIVALS, "demo": [JSON_FILE, MD_FILE]},
        "steps": run.steps,
        "after": after(store),
    }


def after(store: Store) -> dict:
    """The record as the run leaves it: every ticket, the deleted ones' audit lines, the schema versions,
    the accepted files and the approval queue."""
    return {
        "tickets": [ticket(store, t["number"]) for t in store.items("task")],
        "deleted": audit_lines(store),
        "schema_versions": [{"file_kind": v["file_kind"], "version": v["version"], "status": v["status"],
                             "headers": list(v["schema"].names), "ticket": v["ticket"],
                             "drafted_from": v["drafted_from"], "drafted_by": v["drafted_by"],
                             "decided_by": v["decided_by"], "reason": v["reason"]}
                            for v in schemas.versions(store, COMPANY, FILE_KIND)],
        "accepted_files": [{"source_id": f["source_id"], "schema_version": f["schema_version"], "ticket": f["ticket"],
                            "admitted_by": f["admitted_by"], "admitted_at": f["admitted_at"]}
                           for f in accepted.files(store, COMPANY, FILE_KIND)],
        "approval_queue": [{"ticket": p["number"], "action": p["action"]} for p in queue.pending(store)],
    }


# -- demo.md -------------------------------------------------------------------------------------------

def _block(text: str) -> List[str]:
    return ["```text", text, "```"]


def _call(call: dict) -> str:
    """A call as it was made: a command line for a command, otherwise a function or tool call."""
    arguments = call["arguments"]
    if call["kind"] == "command":
        return " ".join([call["call"]] + [f"--{key} {value}" for key, value in arguments.items()])
    shown = ", ".join(f"{key}=" + ("answer" if key == "answer" else json.dumps(value, ensure_ascii=False))
                      for key, value in arguments.items())
    return f"{call['call']}({shown})"


def markdown(run: dict) -> str:
    """demo.json, to read: each step with its ticket's status changes, the calls and their text, the receipt."""
    files = run["files"]
    people = "; ".join(f"{p['name']} ({p['kind']}" + "".join(f", {r}" for r in p["roles"]) + ")" for p in run["people"])
    lines = [f"# {run['title']}", "", run["about"], "",
             f"Written by `{run['written_by']}` from the synthetic company (seed {run['company']['seed']}; the desk's "
             f"date is {run['company']['as_of']}). The record is `{files['store']}`, the company's folder "
             f"`{files['data']}/`, and the files as they arrived `{files['arrivals']}/`. People: {people}.", ""]
    for step in run["steps"]:
        t = step["ticket"]
        lines += [f"## {'Setup' if step['id'] == 'setup' else 'Step ' + step['id']}: {step['title']}", "",
                  f"*{step['date']}.* {step['story']}", "",
                  f"Ticket #{t['number']} ({t['type']}, created by {t['created_by']}): {t['title']}. "
                  f"Status at the end: **{t['status']}**.", "",
                  "| When | Who | Action | Status |", "|---|---|---|---|"]
        for c in step["status_changes"]:
            why = f": {c['reason']}" if c.get("reason") else ""
            moved = f"{c['from']} → {c['to'] or 'deleted'}" if c["from"] else f"→ {c['to']}"
            lines.append(f"| {c['at']} | {c['by']} ({c['role']}) | {c['action']}{why} | {moved} |")
        lines += ["", "What was called, in order, and what came back:", ""]
        for n, c in enumerate(step["calls"], 1):
            lines += [f"**{n}.** {c['at']}, {c['by']}: `{_call(c)}`", ""]
            lines += _block(c["result"]) + [""]
        if step.get("reply"):
            lines += ["The consultant's reply, `answer` above (a fixed text: no model runs):", ""]
            lines += _block(step["reply"]) + [""]
        lines += ["Receipt:", ""] + _block(step["receipt"]) + [""]
    end = run["after"]
    lines += ["## The record after the run", "", "| Ticket | Type | Title | Status |", "|---|---|---|---|"]
    lines += [f"| #{t['number']} | {t['type']} | {t['title']} | {t['status']} |" for t in end["tickets"]]
    lines += [""] + [f"Deleted by the sweep: #{d['ticket']}, closed {d['closed_at']}, deleted {d['deleted_at']} "
                     f"by {d['by']}; its audit line is all the record keeps of it." for d in end["deleted"]]
    lines += ["", "Schema versions:", ""]
    lines += [f"- {v['file_kind']} v{v['version']}, {v['status']}: {', '.join(v['headers'])}. Drafted by "
              f"{v['drafted_by']} on #{v['ticket']}, decided by {v['decided_by']}: {v['reason']}."
              for v in end["schema_versions"]]
    lines += ["", "Accepted files:", ""]
    lines += [f"- {f['source_id']}, under v{f['schema_version']} (#{f['ticket']}), admitted by {f['admitted_by']} at "
              f"{f['admitted_at']}" for f in end["accepted_files"]]
    lines += ["", "Approval queue: " + (", ".join(f"#{p['ticket']} {p['action']}" for p in end["approval_queue"])
                                        or "empty") + "."]
    return "\n".join(lines) + "\n"


def write(out: Path) -> dict:
    """Run the scenario in `out` and write demo.json and demo.md beside the record."""
    fresh(out)
    run = scenario(out)
    (out / JSON_FILE).write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / MD_FILE).write_text(markdown(run), encoding="utf-8", newline="\n")
    return run


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/demo_run.py",
                                     description="Run the synthetic demo scenario once and write it as plain files.")
    parser.add_argument("--out", required=True, type=Path,
                        help="the output directory: new, empty, or an earlier output of this script")
    args = parser.parse_args(argv)
    try:
        run = write(args.out)
    except DemoError as error:
        parser.error(str(error))  # the usage and the reason on stderr, exit code 2
    end = run["after"]
    print(f"demo written to {args.out}: {JSON_FILE}, {MD_FILE}, {STORE}, {DATA}/, {ARRIVALS}/ ({len(run['steps'])} "
          f"steps, {len(end['tickets'])} tickets kept, {len(end['deleted'])} deleted by the sweep)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

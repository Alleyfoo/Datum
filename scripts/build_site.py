"""Build the demo page: one self-contained HTML file drawn from the synthetic run's demo.json.

    python scripts/demo_run.py --out output/demo
    python scripts/build_site.py --demo output/demo/demo.json --out output/site/index.html

The page is a static picture of the record after one run: no script, no external request, no clock.
Every line on it comes from demo.json, so the same run gives the same page byte for byte.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Iterable, List, Optional

STEP_LABELS = {"setup": "Setup", "a": "Step 1", "b": "Step 2", "c": "Step 3", "d": "Step 4"}

OUTCOMES = {
    "no_schema": ("New kind of file", "info"),
    "fits": ("Fits the schema", "good"),
    "structural_change": ("Refused: a column was renamed", "warn"),
}

SHORT = {
    "setup": "First export: the schema is created",
    "a": "Weekly export fits and is admitted",
    "b": "Renamed column refused, schema amended",
    "c": "Customer call answered and approved",
    "d": "Unfinished call closed, then deleted",
}

STATUS_TONE = {
    "open": "info", "in_progress": "busy", "needs_input": "wait",
    "finished": "good", "closed": "bad", "deleted": "gone",
}

CSS = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --ink: #1c2430; --muted: #5b6676; --line: #dde2e8;
  --accent: #2f5bd3; --mono-bg: #f1f3f6;
  --info: #2f5bd3; --info-bg: #e8eefc; --busy: #9a6200; --busy-bg: #fff3dc;
  --wait: #6d3fc0; --wait-bg: #f0e9fc; --good: #1f7a45; --good-bg: #e3f4ea;
  --bad: #b3261e; --bad-bg: #fce8e6; --gone: #5b6676; --gone-bg: #eceff3;
  --warn: #9a6200; --warn-bg: #fff3dc; --old: #b3261e; --new: #1f7a45;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #12161c; --card: #1a2028; --ink: #e6eaf0; --muted: #9aa5b4; --line: #2b333e;
    --accent: #8fb0ff; --mono-bg: #141920;
    --info: #8fb0ff; --info-bg: #1f2a44; --busy: #f2c46d; --busy-bg: #3a2e14;
    --wait: #c3a6ff; --wait-bg: #2c2340; --good: #7fd6a0; --good-bg: #173226;
    --bad: #ff8a80; --bad-bg: #3b1b19; --gone: #9aa5b4; --gone-bg: #242b35;
    --warn: #f2c46d; --warn-bg: #3a2e14; --old: #ff8a80; --new: #7fd6a0;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 920px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 2.4rem; margin: 0; letter-spacing: -0.02em; }
h2 { font-size: 1.35rem; margin: 40px 0 12px; }
h3 { font-size: 1.12rem; margin: 4px 0 6px; }
p { margin: 8px 0; }
.tagline { font-size: 1.15rem; color: var(--muted); margin: 4px 0 16px; }
.lead { font-size: 1.05rem; }
.note { color: var(--muted); font-size: 0.92rem; }
.cast { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 0; padding: 0; list-style: none; }
.cast li { background: var(--card); border: 1px solid var(--line); border-radius: 999px; padding: 4px 12px; font-size: 0.92rem; }
.cast b { font-weight: 600; }
.step { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 20px; margin: 16px 0; }
.step-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px; color: var(--muted); font-size: 0.9rem; }
.step-label { font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.8rem; }
.badge { display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 0.82rem; font-weight: 600; white-space: nowrap; }
.tone-info { color: var(--info); background: var(--info-bg); }
.tone-busy { color: var(--busy); background: var(--busy-bg); }
.tone-wait { color: var(--wait); background: var(--wait-bg); }
.tone-good { color: var(--good); background: var(--good-bg); }
.tone-bad { color: var(--bad); background: var(--bad-bg); }
.tone-gone { color: var(--gone); background: var(--gone-bg); }
.tone-warn { color: var(--warn); background: var(--warn-bg); }
.track { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 14px 0 4px; padding: 0; list-style: none; }
.track li { display: flex; align-items: center; gap: 6px; }
.track .who { color: var(--muted); font-size: 0.8rem; }
.track .arrow { color: var(--muted); }
.headers { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; align-items: center; margin: 14px 0 4px; }
.headers .row { display: flex; flex-wrap: wrap; gap: 6px; }
.cell { border: 1px solid var(--line); border-radius: 6px; padding: 2px 8px; font-size: 0.85rem; background: var(--mono-bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.cell.old { border-color: var(--old); color: var(--old); text-decoration: line-through; }
.cell.new { border-color: var(--new); color: var(--new); font-weight: 600; }
.version { font-size: 0.85rem; color: var(--muted); white-space: nowrap; }
@media (max-width: 560px) { .headers { grid-template-columns: 1fr; } .headers .row { margin-bottom: 6px; } }
pre { background: var(--mono-bg); border: 1px solid var(--line); border-radius: 8px; padding: 12px; overflow-x: auto;
  font: 0.82rem/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre; margin: 8px 0; }
details { margin: 10px 0 0; border-top: 1px solid var(--line); padding-top: 8px; }
summary { cursor: pointer; color: var(--accent); font-weight: 600; font-size: 0.95rem; }
.calls { list-style: none; padding: 0; margin: 8px 0; font-size: 0.88rem; }
.calls li { padding: 6px 0; border-bottom: 1px dashed var(--line); }
.calls code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.85rem; }
.calls .meta { color: var(--muted); font-size: 0.8rem; }
.sweep { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 12px 0 4px; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; margin: 8px 0; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }
.table-wrap { overflow-x: auto; background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 4px 12px; }
.overview { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 16px 0 0; padding: 0; list-style: none; }
.overview a { display: block; height: 100%; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px;
  color: var(--ink); text-decoration: none; }
.overview a:hover { border-color: var(--accent); }
.overview .n { font-size: 0.75rem; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.06em; }
.overview .what { display: block; margin: 4px 0 8px; font-size: 0.92rem; font-weight: 600; line-height: 1.35; }
footer { margin-top: 48px; color: var(--muted); font-size: 0.85rem; border-top: 1px solid var(--line); padding-top: 16px; }
"""


def esc(text: object) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def badge(text: str, tone: str) -> str:
    return f'<span class="badge tone-{esc(tone)}">{esc(text)}</span>'


def status_badge(status: str) -> str:
    return badge(status.replace("_", " "), STATUS_TONE.get(status, "info"))


def first_line(text: str, limit: int = 160) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


def track(changes: Iterable[dict], final: Optional[str]) -> str:
    items: List[str] = []
    for change in changes:
        to = change.get("to")
        if not to:
            continue
        if items:
            items.append('<li class="arrow" aria-hidden="true">→</li>')
        who = change.get("by") or ""
        items.append(f"<li>{status_badge(to)}<span class=\"who\">{esc(change.get('action'))} by {esc(who)}</span></li>")
    if final and final == "deleted":
        items.append('<li class="arrow" aria-hidden="true">→</li>')
        items.append(f"<li>{status_badge('deleted')}<span class=\"who\">by the sweep</span></li>")
    return f'<ul class="track" aria-label="Ticket status changes">{"".join(items)}</ul>' if items else ""


def header_diff(versions: List[dict]) -> str:
    if len(versions) < 2:
        return ""
    old, new = versions[0], versions[1]
    old_cells = []
    new_cells = []
    for name in old["headers"]:
        old_cells.append(f'<span class="cell{" old" if name not in new["headers"] else ""}">{esc(name)}</span>')
    for name in new["headers"]:
        new_cells.append(f'<span class="cell{" new" if name not in old["headers"] else ""}">{esc(name)}</span>')
    return (
        '<div class="headers" aria-label="Schema headers before and after the amendment">'
        f'<span class="version">version {esc(old["version"])} ({esc(old["status"])})</span><div class="row">{"".join(old_cells)}</div>'
        f'<span class="version">version {esc(new["version"])} ({esc(new["status"])})</span><div class="row">{"".join(new_cells)}</div>'
        "</div>"
    )


def calls_block(calls: List[dict]) -> str:
    rows = []
    for call in calls:
        rows.append(
            "<li>"
            f"<code>{esc(call.get('call'))}</code> "
            f"<span class=\"meta\">by {esc(call.get('by'))} · {esc((call.get('at') or '')[:16].replace('T', ' '))}</span>"
            f"<br>{esc(first_line(call.get('result', '')))}"
            "</li>"
        )
    return f"<details><summary>Tool calls ({len(calls)})</summary><ul class=\"calls\">{''.join(rows)}</ul></details>"


def documents_block(documents: List[dict]) -> str:
    if not documents:
        return ""
    rows = "".join(f"<li><b>{esc(d.get('type'))}</b> #{esc(d.get('number'))}: {esc(d.get('title'))}</li>" for d in documents)
    return f"<details><summary>Findings and decisions ({len(documents)})</summary><ul class=\"calls\">{rows}</ul></details>"


def step_card(step: dict, demo: dict) -> str:
    ticket = step.get("ticket") or {}
    status = ticket.get("status")
    if step.get("outcome") in OUTCOMES:
        text, tone = OUTCOMES[step["outcome"]]
        outcome = badge(text, tone)
    elif status:
        outcome = status_badge(status)
    else:
        outcome = ""
    parts = [
        f'<section class="step" id="step-{esc(step["id"])}">',
        '<div class="step-head">'
        f'<span class="step-label">{esc(STEP_LABELS.get(step["id"], step["id"]))}</span>'
        f"<span>{esc(step.get('date'))}</span>"
        + (f"<span>ticket #{esc(ticket.get('number'))}</span>" if ticket else "")
        + f"{outcome}</div>",
        f"<h3>{esc(step.get('title'))}</h3>",
        f"<p>{esc(step.get('story'))}</p>",
        track(step.get("status_changes", []), status),
    ]
    if step["id"] == "b":
        parts.append(header_diff(demo.get("after", {}).get("schema_versions", [])))
    if step.get("reply"):
        parts.append(f"<p class=\"note\">The consultant's reply, drafted from the facts and approved before it could go out:</p><pre>{esc(step['reply'])}</pre>")
    sweep = step.get("sweep")
    if sweep:
        kept = "".join(badge(f"#{n} kept", "good") for n in sweep.get("kept_finished", []))
        gone = "".join(badge(f"#{n} deleted", "gone") for n in sweep.get("deleted", []))
        parts.append(f'<div class="sweep"><span class="note">Sweep on {esc(sweep.get("on"))}:</span>{gone}{kept}</div>')
    if step.get("receipt"):
        label = "Receipt" if step["id"] == "c" else "What the record says"
        parts.append(f"<details{' open' if step['id'] == 'c' else ''}><summary>{label}</summary><pre>{esc(step['receipt'])}</pre></details>")
    parts.append(documents_block(step.get("documents", [])))
    parts.append(calls_block(step.get("calls", [])))
    parts.append("</section>")
    return "".join(parts)


def overview(demo: dict) -> str:
    tiles = []
    for step in demo.get("steps", []):
        ticket = step.get("ticket") or {}
        status = ticket.get("status")
        tag = status_badge(status) if status else ""
        tiles.append(
            f'<li><a href="#step-{esc(step["id"])}"><span class="n">{esc(STEP_LABELS.get(step["id"], step["id"]))}</span>'
            f'<span class="what">{esc(SHORT.get(step["id"], step.get("title")))}</span>{tag}</a></li>'
        )
    return f'<ul class="overview" aria-label="The run at a glance">{"".join(tiles)}</ul>'


def after_block(demo: dict) -> str:
    after = demo.get("after", {})
    tickets = after.get("tickets", [])
    rows = "".join(
        f"<tr><td>#{esc(t.get('number'))}</td><td>{esc(t.get('type'))}</td><td>{status_badge(t.get('status', ''))}</td>"
        f"<td>{esc(t.get('title'))}</td><td>{esc(t.get('created_by'))}</td></tr>"
        for t in tickets
    )
    deleted = "".join(
        f"<li>Ticket #{esc(d.get('ticket'))}: closed {esc((d.get('closed_at') or '')[:10])}, deleted {esc((d.get('deleted_at') or '')[:10])}."
        " Only this audit line remains.</li>"
        for d in after.get("deleted", [])
    )
    queue = after.get("approval_queue", [])
    return (
        "<h2>The record after the run</h2>"
        f'<div class="table-wrap"><table><thead><tr><th>Ticket</th><th>Type</th><th>Status</th><th>Title</th><th>Created by</th></tr></thead><tbody>{rows}</tbody></table></div>'
        + (f"<ul class=\"calls\">{deleted}</ul>" if deleted else "")
        + f"<p class=\"note\">{len(after.get('accepted_files', []))} files admitted · "
        f"{len(after.get('schema_versions', []))} schema versions · "
        f"{len(queue)} replies waiting for approval.</p>"
    )


def build(demo: dict) -> str:
    cast = "".join(
        f"<li><b>{esc(p.get('name'))}</b> · {esc(', '.join(p.get('roles') or []) or p.get('kind'))}</li>"
        for p in demo.get("people", [])
    )
    steps = "".join(step_card(step, demo) for step in demo.get("steps", []))
    company = demo.get("company", {})
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Datum demo</title>"
        f"<style>{CSS}</style></head><body><main>"
        "<header><h1>Datum</h1>"
        "<p class=\"tagline\">A governed record for company data, from intake to decision.</p>"
        "<p class=\"lead\">One synthetic run, replayed: a supplier's weekly stock export, a renamed column, "
        "a customer call, and a ticket that could not be finished. Every line below comes from the record.</p>"
        f"<p class=\"note\">Synthetic company <b>{esc(company.get('id'))}</b>, seed {esc(company.get('seed'))}, as of "
        f"{esc(company.get('as_of'))}. No model ran: the tools and rules produced every answer, and a named person made "
        "every decision.</p>"
        f"<ul class=\"cast\" aria-label=\"People and services in the run\">{cast}</ul></header>"
        "<h2>The run at a glance</h2>"
        f"{overview(demo)}"
        "<h2>What happened</h2>"
        f"{steps}"
        f"{after_block(demo)}"
        "<footer>Generated by <code>scripts/build_site.py</code> from <code>demo.json</code>, written by "
        f"<code>{esc(demo.get('written_by'))}</code>.</footer>"
        "</main></body></html>\n"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static demo page from demo.json.")
    parser.add_argument("--demo", required=True, help="path to demo.json written by scripts/demo_run.py")
    parser.add_argument("--out", required=True, help="the HTML file to write")
    args = parser.parse_args(argv)
    source = Path(args.demo)
    if not source.is_file():
        print(f"build_site: no demo.json at {source}", file=sys.stderr)
        return 1
    page = build(json.loads(source.read_text(encoding="utf-8")))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8", newline="\n")
    print(f"demo page written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

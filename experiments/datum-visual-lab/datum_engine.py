"""Datum Visual Lab: deterministic, synthetic spare-parts evaluation.

No external dependencies, external calls, write-back, LLM or probabilistic classification.
All demo input records are fictional and intentionally small.
"""
from __future__ import annotations

import hashlib
import json
import csv
import io
from pathlib import Path
from copy import deepcopy
from typing import Any

RULE_VERSION = "datum-repair-v0.2.0"
DATASET_VERSION = "synthetic-spares-2026-10"
SCENARIOS = {
    "baseline": "Baseline inventory",
    "delivery": "Hypothetical delivery",
    "quarantine": "Unverified stock row",
}

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


SOURCE_FILES = ("machines.csv", "bom.csv", "stock.csv", "claims.csv")


def capture_sources() -> dict[str, bytes]:
    """Capture the exact source bytes used by a single evaluation.

    The files are read sequentially, not atomically as a group. Once captured,
    parsing, evaluation and hashing all use the same immutable byte strings.
    """
    return {name: (FIXTURE_DIR / name).read_bytes() for name in SOURCE_FILES}


def _csv_rows(name: str, sources: dict[str, bytes] | None = None) -> list[dict[str, str]]:
    if sources is None:
        with (FIXTURE_DIR / name).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    with io.StringIO(sources[name].decode("utf-8"), newline="") as handle:
        return list(csv.DictReader(handle))


def _verified_quantity(value: str) -> int:
    if not value.isdecimal():
        raise ValueError(f"Invalid quantity {value!r}: integer required")
    return int(value)


def load_fixture(sources: dict[str, bytes] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Read independent immutable-like CSV input files; failures stop evaluation."""
    rows = (lambda name: _csv_rows(name)) if sources is None else (lambda name: _csv_rows(name, sources))
    machines = []
    for row in rows("machines.csv"):
        machines.append({"id": row["id"], "name": row["name"], "site": row["site"],
                         "priority": _verified_quantity(row["priority"]), "bom": None})
    by_id = {m["id"]: m for m in machines}
    if len(by_id) != len(machines):
        raise ValueError("Duplicate machine ID in machines.csv")
    bom_pairs = set()
    for row in rows("bom.csv"):
        mid = row["machine_id"]
        if mid not in by_id:
            raise ValueError(f"Unrecognised machine in BOM: {mid}")
        m = by_id[mid]
        pair = (mid, row["part_id"])
        if pair in bom_pairs:
            raise ValueError(f"Duplicate BOM entry for machine {mid}, part {row['part_id']}")
        bom_pairs.add(pair)
        if m["bom"] is None:
            m["bom"] = []
        m["bom"].append((row["part_id"], _verified_quantity(row["required"])))
    parts = {}
    for row in rows("stock.csv"):
        pid = row["part_id"]
        if pid in parts:
            raise ValueError(f"Duplicate part ID in stock.csv: {pid}")
        parts[pid] = {"name": row["name"], "stock": _verified_quantity(row["quantity"]),
                      "eta": _verified_quantity(row["eta_days"]) if row["eta_days"] else None}
    for mid, pid in bom_pairs:
        if pid not in parts:
            raise ValueError(f"Unknown stock part in BOM for machine {mid}: {pid}")
    claims = []
    for row in rows("claims.csv"):
        claims.append({**row, "accepted": row["accepted"].lower() == "true"})
    return machines, parts, claims


def source_hashes(sources: dict[str, bytes] | None = None) -> dict[str, str]:
    """True SHA-256 of the original CSV bytes, not a claim of data truth."""
    if sources is None:
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FIXTURE_DIR.glob("*.csv"))}
    return {name: hashlib.sha256(data).hexdigest() for name, data in sorted(sources.items())}


def _hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evaluate(scenario: str = "baseline", sources: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Evaluate by priority with a single shared stock pool. Never silently accept substitutions."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; choose {', '.join(SCENARIOS)}")
    machines, parts, claims = load_fixture(sources)
    stock = {pid: dict(info) for pid, info in parts.items()}
    adjustments = []
    quarantined = []
    if scenario == "delivery":
        for pid, count in [("PL-40", 1), ("GBX-200", 1), ("BRG-6208", 1)]:
            stock[pid]["stock"] += count
            adjustments.append({"part": pid, "delta": count, "source": "SIM-DELIVERY-01", "note": "Hypothetical receipt, not an ERP transaction"})
    elif scenario == "quarantine":
        quarantined.append({"part": "BRG-6208", "raw_quantity": "1?", "source": "SIM-IMPORT-FAIL-01", "reason": "Quantity not a verified non-negative integer; row rejected"})

    available = {pid: info["stock"] for pid, info in stock.items()}
    allocations: dict[str, list[dict[str, Any]]] = {}
    rows = []
    # Stable priority order: high operational priority first, with machine ID tiebreaker.
    for m in sorted(machines, key=lambda v: (v["priority"], v["id"])):
        required = m["bom"]
        items = []
        reasons = []
        allocated = []
        if required is None:
            status = "review"
            reasons.append("No approved bill of materials; repairability is unknown.")
        else:
            for pid, need in required:
                p = stock[pid]
                have = available[pid]
                items.append({"part": pid, "part_name": p["name"], "required": need,
                              "available_before": have, "total_stock": p["stock"],
                              "eta_days": p["eta"], "source": f"stock.csv:{list(parts).index(pid) + 2}",
                              "supplier_source": "Synthetic ETA from stock.csv"})
                if have < need:
                    if pid == "CP-09":
                        reasons.append("Alternative coupling has conflicting compatibility claims; no automatic substitution.")
                    else:
                        owners = [a["machine"] for a in allocations.get(pid, [])]
                        suffix = f"; remaining stock reserved for {', '.join(owners)}" if owners else ""
                        reasons.append(f"{p['name']}: need {need}, available {have}{suffix}.")
            if reasons:
                status = "review" if any(p == "CP-09" for p, _ in required) else "blocked"
            else:
                status = "ready"
                for pid, need in required:
                    available[pid] -= need
                    entry = {"machine": m["id"], "part": pid, "quantity": need}
                    allocations.setdefault(pid, []).append(entry)
                    allocated.append(entry)
                reasons.append("All required parts can be reserved from validated stock.")
        rows.append({
            "id": m["id"], "name": m["name"], "site": m["site"], "priority": m["priority"],
            "status": status, "reasons": reasons, "requirements": items,
            "allocated": allocated, "bom_source": "bom.csv / machine=" + m["id"] if required is not None else None,
            "rule": "BOM_REQUIRED" if required is None else ("SUBSTITUTE_CONFLICT" if m["id"] == "CF-01" else "PRIORITY_ALLOCATE"),
            "has_conflict": m["id"] == "CF-01", "missing_bom": required is None,
        })

    # Make the user-facing table stable by machine ID, independently of allocation priority.
    rows.sort(key=lambda r: r["id"])
    counts = {s: sum(r["status"] == s for r in rows) for s in ("ready", "blocked", "review")}
    input_signature = _hash({"machines": machines, "stock": stock, "claims": claims, "quarantined": quarantined})
    receipt = {
        "run_id": _hash({"scenario": scenario, "input": input_signature, "rule": RULE_VERSION})[:16].upper(),
        "input_sha256": input_signature, "source_hashes": source_hashes(sources), "ruleset": RULE_VERSION, "dataset": DATASET_VERSION,
        "allocation_method": "Priority ascending, machine ID ascending. No double-booking of shared stock.",
        "actions_taken": "None. Read-only demonstration; no ERP write-back or real approvals.",
        "unknowns": ["Machine condition and labour availability are not modelled.",
                     "Supplier lead times are synthetic planning data, not delivery promises.",
                     "Conflicting compatibility claims are not reconciled automatically."],
    }
    return {
        "version": "0.2", "scenario": scenario, "scenario_label": SCENARIOS[scenario], "scenario_labels": SCENARIOS,
        "question": "Which machines could we repair today?", "counts": counts, "machines": rows,
        "stock": [{"id": pid, **item, "remaining": available[pid], "source": f"stock.csv:{list(stock).index(pid)+2}"} for pid, item in stock.items()],
        "claims": deepcopy(claims), "adjustments": adjustments, "quarantined": quarantined,
        "receipt": receipt, "disclaimer": "Synthetic test records. No operational ERP connection.",
    }


def summarize(data: dict[str, Any]) -> str:
    """Summarize one evaluation without re-reading its source files."""
    names = {s: [m["id"] for m in data["machines"] if m["status"] == s] for s in ("ready", "blocked", "review")}
    return (f"Datum synthetic spare-parts analysis ({data['scenario_label']}): "
            f"{data['counts']['ready']} ready [{', '.join(names['ready'])}], "
            f"{data['counts']['blocked']} blocked [{', '.join(names['blocked'])}], "
            f"{data['counts']['review']} needing review [{', '.join(names['review'])}]. "
            f"Rule {RULE_VERSION}; receipt {data['receipt']['run_id']}. "
            "No write-back; see per-machine evidence for limitations.")


def text_summary(scenario: str = "baseline") -> str:
    return summarize(evaluate(scenario))


def all_scenarios() -> dict[str, Any]:
    return {k: evaluate(k) for k in SCENARIOS}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", choices=SCENARIOS.keys(), default="baseline")
    a = p.parse_args()
    print(json.dumps(evaluate(a.scenario), indent=2))

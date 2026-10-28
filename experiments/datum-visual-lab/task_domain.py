"""Shared deterministic operations for read-only synthetic task investigations.

These functions are used by both MCP clients and the task UI. Source bytes are
captured once per operation; no substitution or equipment suitability is inferred.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

import datum_engine as engine

TaskType = Literal["repair_investigation", "supplier_conflict_review"]
Strategy = Literal["baseline", "delivery"]
DOMAIN_VERSION = "datum-task-investigation-v0.1"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _sources(sources: dict[str, bytes] | None) -> dict[str, bytes]:
    return engine.capture_sources() if sources is None else dict(sources)


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a non-empty identifier without surrounding whitespace")
    return value


def get_machine(machine_id: str, sources: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Return a known synthetic machine and its source reference; unknown IDs fail."""
    machine_id = _id(machine_id, "machine_id")
    machines, _, _ = engine.load_fixture(_sources(sources))
    for row, machine in enumerate(machines, start=2):
        if machine["id"] == machine_id:
            return {"id": machine_id, "name": machine["name"], "site": machine["site"],
                    "priority": machine["priority"], "source": f"machines.csv:{row}"}
    raise ValueError(f"Unknown machine: {machine_id}")


def get_required_parts(machine_id: str, sources: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Return known BOM requirements, distinguishing absent BOM from an empty list."""
    sources = _sources(sources)
    get_machine(machine_id, sources)
    machines, parts, _ = engine.load_fixture(sources)
    machine = next(m for m in machines if m["id"] == machine_id)
    if machine["bom"] is None:
        return {"machine_id": machine_id, "known": False, "requirements": [], "source": None}
    return {"machine_id": machine_id, "known": True,
            "requirements": [{"part_id": pid, "name": parts[pid]["name"], "required": count} for pid, count in machine["bom"]],
            "source": f"bom.csv / machine={machine_id}"}


def check_inventory(part_ids: list[str], sources: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Return recorded stock, not priority allocation or a reservation."""
    if not isinstance(part_ids, list) or not part_ids or any(not isinstance(p, str) for p in part_ids):
        raise ValueError("part_ids must be a non-empty list of identifiers")
    _, parts, _ = engine.load_fixture(_sources(sources))
    result = []
    for part_id in part_ids:
        _id(part_id, "part_id")
        if part_id not in parts:
            raise ValueError(f"Unknown part: {part_id}")
        result.append({"part_id": part_id, **parts[part_id], "source": f"stock.csv:{list(parts).index(part_id) + 2}"})
    return {"parts": result, "meaning": "Recorded total stock, before simulated priority allocation; not an ERP reservation."}


def find_alternatives(part_id: str, sources: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Return claim records mentioning a required part, without deciding compatibility.

    The fixture has no structured alternative mapping. Matching a whole identifier
    in a claim's 'about' text only locates possible evidence; it proves no fit.
    """
    part_id = _id(part_id, "part_id")
    _, parts, claims = engine.load_fixture(_sources(sources))
    if part_id not in parts:
        raise ValueError(f"Unknown part: {part_id}")
    pattern = re.compile(r"(?<![A-Za-z0-9-])" + re.escape(part_id) + r"(?![A-Za-z0-9-])")
    matches = [{**claim, "record_source": f"claims.csv:{i}"} for i, claim in enumerate(claims, start=2)
               if pattern.search(claim["about"])]
    return {"part_id": part_id, "claim_records": matches,
            "finding": "unverified_claims" if matches else "unknown",
            "explanation": "Claims are evidence to inspect, not approved substitution or proof that no alternatives exist."}


def evaluate_task(task_type: TaskType, parameters: dict[str, Any], sources: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Evaluate one task on a captured set of exact source bytes, without writes."""
    sources = _sources(sources)
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    if task_type == "repair_investigation":
        if set(parameters) != {"machine_id", "strategy", "allow_substitutes"}:
            raise ValueError("repair parameters require machine_id, strategy and allow_substitutes")
        mid = _id(parameters["machine_id"], "machine_id")
        strategy = parameters["strategy"]
        if strategy not in ("baseline", "delivery"):
            raise ValueError("strategy must be baseline or delivery")
        if not isinstance(parameters["allow_substitutes"], bool):
            raise ValueError("allow_substitutes must be a boolean")
        machine_info = get_machine(mid, sources)
        requirements = get_required_parts(mid, sources)
        outcome = engine.evaluate(strategy, sources)
        machine = next(m for m in outcome["machines"] if m["id"] == mid)
        alternatives = [find_alternatives(item["part_id"], sources) for item in requirements["requirements"]]
        relevant_ids = {r["part_id"] for r in requirements["requirements"]}
        stock = [row for row in outcome["stock"] if row["id"] in relevant_ids]
        unresolved = list(outcome["receipt"]["unknowns"]) + [
            "No verified substitute mapping is modelled; enabling substitutions does not apply one.",
            "No matching alternative claim does not establish that alternatives do not exist.",
            "The inherited CP-09/CF-01 conflict rule is fixture-specific and is not a general compatibility rule.",
        ]
        conclusion = {"status": machine["status"], "reasons": machine["reasons"],
                      "scope": "Synthetic stock readiness under the selected scenario, not operational repair approval.",
                      "substitution_applied": False}
        evidence = {"machine": machine_info, "requirements": requirements, "evaluation_machine": machine,
                    "stock": stock, "adjustments": outcome["adjustments"]}
        receipt = dict(outcome["receipt"])
    elif task_type == "supplier_conflict_review":
        if set(parameters) != {"part_id"}:
            raise ValueError("supplier conflict parameters require part_id")
        part_id = _id(parameters["part_id"], "part_id")
        _, parts, claims = engine.load_fixture(sources)
        if part_id not in parts:
            raise ValueError(f"Unknown part: {part_id}")
        matches = [{**c, "record_source": f"claims.csv:{i}"} for i, c in enumerate(claims, start=2) if c["part"] == part_id]
        differing = len({c["claim"] for c in matches}) > 1
        conclusion = {"status": "review" if matches else "unknown", "conflicting_claims": differing,
                      "scope": "Claims are retained as evidence; no compatibility determination is made."}
        evidence = {"part_id": part_id, "claims": matches, "stock": check_inventory([part_id], sources)["parts"]}
        alternatives = []
        unresolved = ["Supplier claims have not been independently verified.", "No compatibility approval is recorded."]
        receipt = {"source_hashes": engine.source_hashes(sources), "input_sha256": _hash(engine.source_hashes(sources)),
                   "ruleset": DOMAIN_VERSION, "dataset": engine.DATASET_VERSION,
                   "actions_taken": "None. Read-only demonstration; no ERP write-back or real approvals."}
    else:
        raise ValueError(f"Unknown task type: {task_type}")
    normalized = dict(parameters)
    receipt["task_rule_version"] = DOMAIN_VERSION
    receipt["parameters"] = normalized
    receipt["run_id"] = _hash({"task_type": task_type, "parameters": normalized,
                               "source_hashes": receipt["source_hashes"], "task_rule_version": DOMAIN_VERSION,
                               "engine_rule_version": receipt["ruleset"]})[:16].upper()
    return {"task_type": task_type, "parameters": normalized, "conclusion": conclusion,
            "evidence": evidence, "alternatives": alternatives, "receipt": receipt, "unresolved": unresolved}


def list_machines(sources: dict[str, bytes] | None = None) -> list[dict[str, Any]]:
    """Discover machines from the captured synthetic data."""
    machines, _, _ = engine.load_fixture(_sources(sources))
    return [{"id": m["id"], "name": m["name"], "site": m["site"]} for m in machines]


def list_claim_parts(sources: dict[str, bytes] | None = None) -> list[str]:
    """Discover the candidate parts named in existing claim records."""
    _, _, claims = engine.load_fixture(_sources(sources))
    return sorted({c["part"] for c in claims})


def compare_strategies(machine_id: str, allow_substitutes: bool, sources: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Compare both available synthetic stock scenarios using exactly one capture."""
    sources = _sources(sources)
    results = [evaluate_task("repair_investigation", {"machine_id": machine_id, "strategy": strategy,
              "allow_substitutes": allow_substitutes}, sources) for strategy in ("baseline", "delivery")]
    return {"machine_id": machine_id, "results": results,
            "scope": "Delivery is hypothetical. No substitute is applied or approved."}

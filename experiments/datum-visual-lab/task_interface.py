"""Compose a bounded, data-only interface for the persistent task experiment.

The browser interprets the five component types below, never executable code.
Task-specific mapping stays here, outside the shared business-rule module.
"""
from __future__ import annotations

import csv
from typing import Any
import datum_engine

COMPONENT_TYPES = frozenset({"parameter_form", "data_table", "evidence_graph", "status_summary", "decision_receipt"})


def _options(values: list[tuple[str, str]], current: str, unavailable: bool = False) -> list[dict[str, str]]:
    # Keep a formerly valid selection visible if the current fixture changed.
    if current and current not in {v for v, _ in values}:
        suffix = "current source unavailable" if unavailable else "not present in current source"
        values = [(current, f"{current} ({suffix})")] + values
    return [{"value": value, "label": label} for value, label in values]


def _form(label: str, task_id: str, fields: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    return {"fields": fields, "action": {"tool": tool, "label": label, "arguments": {"task_id": task_id}}}


def _table(columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"columns": [{"key": key, "label": label} for key, label in columns], "rows": rows}


def _receipt(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {"items": [], "notes": ["No evaluation has been recorded yet."]}
    r = result["receipt"]
    return {"items": [{"label": "Run identifier", "value": r.get("run_id")},
                      {"label": "Rule version", "value": r.get("ruleset")},
                      {"label": "Task rule version", "value": r.get("task_rule_version")},
                      {"label": "Parameters", "value": r.get("parameters")},
                      {"label": "Input signature SHA-256", "value": r.get("input_sha256")},
                      {"label": "Source file SHA-256", "value": r.get("source_hashes")},
                      {"label": "Actions taken", "value": r.get("actions_taken")}],
            "notes": result.get("unresolved", [])}


def build_interface(task: dict[str, Any], requested_components: list[str] | None = None) -> dict[str, Any]:
    """Render a stored task as a validated, non-executable component description.

    Requested component types are a filter, not arbitrary UI or action definitions.
    Unknown names and types unavailable for the task are rejected.
    """
    task_id = task["task_id"]
    task_type = task["task_type"]
    params = task["parameters"]
    result = task.get("current_result")
    data: dict[str, Any] = {}
    components: list[dict[str, str]] = []

    def add(kind: str, title: str, source: str, value: dict[str, Any]) -> None:
        if kind not in COMPONENT_TYPES or source in data:
            raise ValueError("Invalid component definition")
        components.append({"type": kind, "title": title, "source": source})
        data[source] = value

    # A persisted task must remain inspectable even if today's source files are
    # missing or invalid. Only selector options use live source data; the
    # displayed conclusions, receipts and evidence come from the stored result.
    try:
        machines, parts, _ = datum_engine.load_fixture()
        source_warning = []
    except (OSError, ValueError, KeyError, UnicodeError, csv.Error):
        machines, parts = [], {}
        source_warning = ["Current source data is unavailable or invalid; saved evidence is still shown. Re-evaluation requires valid current sources."]
    title = "Repair readiness investigation" if task_type == "repair_investigation" else "Supplier record conflict review"
    conclusion = result.get("conclusion", {}) if result else {}
    status_items = [{"label": "Deterministic result", "value": conclusion.get("status", "Not evaluated")},
                    {"label": "Rule reasons", "value": conclusion.get("reasons", "See supplier records and receipt")},
                    {"label": "Scope", "value": conclusion.get("scope", "No evaluation recorded yet.")},
                    {"label": "Agent recommendation (unverified)", "value": task.get("recommendation") or "None recorded"},
                    {"label": "Proposed next steps", "value": task.get("next_steps") or "None recorded"},
                    {"label": "Authorization", "value": "None; review is a local record only."}]
    add("status_summary", "Task status and handoff", "status", {"items": status_items, "notes": source_warning + task.get("outstanding_questions", [])})

    if task_type == "repair_investigation":
        machine_options = _options([(m["id"], f"{m['id']} — {m['name']}") for m in machines], params.get("machine_id", ""), bool(source_warning))
        fields = [{"name": "machine_id", "label": "Machine", "type": "select", "value": params.get("machine_id"), "options": machine_options, "required": True},
                  {"name": "strategy", "label": "Scenario", "type": "select", "value": params.get("strategy"), "options": [{"value": "baseline", "label": "Baseline"}, {"value": "delivery", "label": "Hypothetical delivery"}], "required": True},
                  {"name": "allow_substitutes", "label": "Consider substitute evidence", "type": "checkbox", "value": params.get("allow_substitutes", False)}]
        add("parameter_form", "Investigation parameters", "parameters", _form("Evaluate", task_id, fields, "datum_task_ui_evaluate"))
        evidence = result.get("evidence", {}) if result else {}
        machine = evidence.get("machine", {})
        req = evidence.get("evaluation_machine", {}).get("requirements", [])
        nodes = []
        edges = []
        if machine:
            nodes.append({"id": "machine", "label": machine["id"], "detail": f"{machine['name']} · {machine['source']}"})
            for i, row in enumerate(req):
                part_key = f"part-{i}"
                nodes.append({"id": part_key, "label": row["part"], "detail": f"Required {row['required']}; available before allocation {row['available_before']}; {row['source']}"})
                edges.append({"from": "machine", "to": part_key, "label": "requires"})
        add("evidence_graph", "Machine dependency evidence", "evidence_graph", {"nodes": nodes, "edges": edges})
        add("data_table", "Required parts and stock evidence", "requirements", _table(
            [("part", "Part"), ("part_name", "Name"), ("required", "Required"), ("available_before", "Available before allocation"), ("source", "Source")], req))
        alternatives = result.get("alternatives", []) if result else []
        alt_rows = [{"part": item.get("part_id"), "finding": item.get("finding"),
                     "claims": item.get("claim_records"), "explanation": item.get("explanation")} for item in alternatives]
        add("data_table", "Alternative evidence (not approval)", "alternatives", _table(
            [("part", "Required part"), ("finding", "Finding"), ("claims", "Claim records"), ("explanation", "Interpretation")], alt_rows))
    elif task_type == "supplier_conflict_review":
        choices = _options([(pid, f"{pid} — {info['name']}") for pid, info in parts.items()], params.get("part_id", ""), bool(source_warning))
        fields = [{"name": "part_id", "label": "Part", "type": "select", "value": params.get("part_id"), "options": choices, "required": True}]
        add("parameter_form", "Supplier record parameters", "parameters", _form("Compare claims", task_id, fields, "datum_task_ui_evaluate"))
        claims = result.get("evidence", {}).get("claims", []) if result else []
        add("data_table", "Supplier claims and provenance", "claims", _table(
            [("id", "Record"), ("claim", "Claim"), ("about", "About"), ("source", "Supplier source"), ("record_source", "Record reference"), ("accepted", "Accepted")], claims))
    else:
        raise ValueError("Unknown task type")

    if source_warning:
        data["parameters"]["action"].update({
            "enabled": False,
            "disabled_reason": "Re-evaluation is unavailable until valid source data is restored.",
        })

    add("decision_receipt", "Decision receipt and uncertainty", "receipt", _receipt(result))
    history = [{"evaluation_id": x["evaluation_id"], "created_at": x["created_at"], "initiator": x["initiator"],
                "parameters": x["parameters"], "status": x["result"].get("conclusion", {}).get("status"),
                "run_id": x["result"].get("receipt", {}).get("run_id")} for x in task.get("evaluations", [])]
    add("data_table", "Evaluation history", "history", _table(
        [("evaluation_id", "Evaluation"), ("created_at", "Recorded"), ("initiator", "Initiator label"), ("parameters", "Parameters"), ("status", "Result"), ("run_id", "Receipt")], history))
    reviews = task.get("reviews", [])
    add("data_table", "Local human review history", "reviews", _table(
        [("review_id", "Review"), ("evaluation_id", "Evaluation"), ("decision", "Review"), ("note", "Note"), ("created_at", "Recorded")], reviews))
    if history:
        review_fields = [{"name": "decision", "label": "Review", "type": "select", "value": "needs_more_information", "required": True,
                          "options": [{"value": "reviewed", "label": "Reviewed"}, {"value": "needs_more_information", "label": "Needs more information"}, {"value": "disagree", "label": "Disagree"}]},
                         {"name": "note", "label": "Review note", "type": "textarea", "value": ""}]
        review_form = _form("Record review", task_id, review_fields, "datum_task_ui_review")
        review_form["action"]["arguments"]["evaluation_id"] = history[-1]["evaluation_id"]
        add("parameter_form", "Record local review (not an approval)", "review", review_form)

    if requested_components is not None:
        if not isinstance(requested_components, list) or any(not isinstance(x, str) for x in requested_components):
            raise ValueError("requested_components must be a list of supported component types")
        available = {c["type"] for c in components}
        if len(set(requested_components)) != len(requested_components) or not set(requested_components) <= COMPONENT_TYPES or not set(requested_components) <= available:
            raise ValueError("Unsupported, duplicate, or unavailable component type")
        # The requested order controls groups; same-type components retain their Python-defined order.
        components = [c for kind in requested_components for c in components if c["type"] == kind]
        data = {c["source"]: data[c["source"]] for c in components}
    return {"schema_version": "datum-task-ui-v1", "task_id": task_id, "task_type": task_type,
            "title": title, "components": components, "data": data}

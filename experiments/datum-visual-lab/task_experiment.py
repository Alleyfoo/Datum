"""MCP bindings for the persistent task experiment.

The agent-facing tools and app-only tools call the same Python domain and store
functions. Initiator labels are claims, not authentication or authorization.
"""
from pathlib import Path
from typing import Literal

from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import StrictBool, StrictInt

import task_domain as domain
import task_interface
from task_store import TaskStore

URI = "ui://datum/task-experiment"
TaskType = Literal["repair_investigation", "supplier_conflict_review"]
Strategy = Literal["baseline", "delivery"]
Review = Literal["reviewed", "needs_more_information", "disagree"]


def _result(data: dict, label: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=label)], structured_content=data)


def _parameters(task_type: str, machine_id: str | None, strategy: Strategy | None,
                allow_substitutes: bool | None, part_id: str | None) -> dict:
    if task_type == "repair_investigation":
        if machine_id is None or strategy is None or allow_substitutes is None or part_id is not None:
            raise ValueError("Repair requires machine_id, strategy and allow_substitutes; part_id is not allowed")
        return {"machine_id": machine_id, "strategy": strategy, "allow_substitutes": allow_substitutes}
    if task_type == "supplier_conflict_review":
        if part_id is None or machine_id is not None or strategy is not None or allow_substitutes is not None:
            raise ValueError("Supplier review requires part_id only")
        return {"part_id": part_id}
    raise ValueError("Unknown task type")


def _evaluate(task_id: str, machine_id: str | None, strategy: Strategy | None,
              allow_substitutes: bool | None, part_id: str | None,
              initiator: str, tool_name: str, expected_revision: int | None = None) -> dict:
    store = TaskStore()
    store.record_tool_invocation(task_id, tool_name, initiator)
    task = store.get(task_id)
    params = _parameters(task["task_type"], machine_id, strategy, allow_substitutes, part_id)
    result = domain.evaluate_task(task["task_type"], params)
    return store.evaluate(task_id, params, result, initiator, expected_revision=expected_revision)


def datum_list_machines() -> CallToolResult:
    """List synthetic machines and their identifiers."""
    return _result({"machines": domain.list_machines()}, "Synthetic machine list")


def datum_get_machine(machine_id: str) -> CallToolResult:
    """Get one synthetic machine; unknown machine identifiers are rejected."""
    return _result(domain.get_machine(machine_id), "Synthetic machine record")


def datum_get_required_parts(machine_id: str) -> CallToolResult:
    """Read a machine's requirements; an absent BOM is explicitly unknown."""
    return _result(domain.get_required_parts(machine_id), "Synthetic machine requirements")


def datum_check_inventory(part_ids: list[str]) -> CallToolResult:
    """Read recorded stock for known part IDs, before simulated allocation."""
    return _result(domain.check_inventory(part_ids), "Synthetic recorded stock")


def datum_find_alternatives(part_id: str) -> CallToolResult:
    """Find possible claim evidence; it never establishes compatibility or substitutes."""
    return _result(domain.find_alternatives(part_id), "Unverified alternative evidence")


def datum_compare_strategies(machine_id: str, allow_substitutes: StrictBool) -> CallToolResult:
    """Compare baseline and hypothetical delivery on the same captured input bytes."""
    return _result(domain.compare_strategies(machine_id, allow_substitutes), "Synthetic strategy comparison")


def datum_task_create(task_type: TaskType, machine_id: str | None = None,
                      strategy: Strategy | None = None, allow_substitutes: StrictBool | None = None,
                      part_id: str | None = None, recommendation: str | None = None,
                      next_steps: list[str] | None = None) -> CallToolResult:
    """Create a persistent synthetic task; recommendation is unverified text, not approval.

    Repair parameters must include machine_id, strategy and allow_substitutes. Supplier
    conflict review requires part_id alone. Run datum_task_evaluate afterwards.
    """
    params = _parameters(task_type, machine_id, strategy, allow_substitutes, part_id)
    domain.evaluate_task(task_type, params)  # Validate against source data before persistence.
    store = TaskStore()
    task = store.create(task_type, params, "agent", recommendation, next_steps)
    store.record_tool_invocation(task["task_id"], "datum_task_create", "agent")
    return _result(store.get(task["task_id"]), "Local synthetic task created; no business authorization")


def datum_task_evaluate(task_id: str, machine_id: str | None = None,
                        strategy: Strategy | None = None, allow_substitutes: StrictBool | None = None,
                        part_id: str | None = None) -> CallToolResult:
    """Evaluate explicit task parameters and append a receipt; no ERP action occurs."""
    state = _evaluate(task_id, machine_id, strategy, allow_substitutes, part_id, "agent", "datum_task_evaluate")
    return _result(state, "Deterministic evaluation recorded in local task history")


def datum_task_get(task_id: str) -> CallToolResult:
    """Read persistent task, all evaluation receipts, review records and audit events."""
    store = TaskStore()
    store.record_tool_invocation(task_id, "datum_task_get", "agent")
    return _result(store.get(task_id), "Local synthetic task state")


def datum_task_open(task_id: str, requested_components: list[str] | None = None) -> CallToolResult:
    """Open a task as a server-composed interface; optional component types are validated."""
    store = TaskStore()
    store.record_tool_invocation(task_id, "datum_task_open", "agent")
    task = store.get(task_id, reopen=True, initiator="agent")
    return _result(task_interface.build_interface(task, requested_components), "Local task interface; review is not authorization")


def datum_task_ui_evaluate(task_id: str, machine_id: str | None = None,
                           strategy: Strategy | None = None, allow_substitutes: StrictBool | None = None,
                           part_id: str | None = None, expected_revision: StrictInt | None = None) -> CallToolResult:
    """App-only: evaluate exactly the same shared rules and update the local task."""
    try:
        state = _evaluate(task_id, machine_id, strategy, allow_substitutes, part_id, "human", "datum_task_ui_evaluate", expected_revision)
    except ValueError as exc:
        return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)
    return _result(task_interface.build_interface(state), "Synthetic evaluation complete; no ERP write")


def datum_task_ui_review(task_id: str, evaluation_id: str, decision: Review, note: str) -> CallToolResult:
    """App-only: record an unverified human-labelled review, never an approval."""
    store = TaskStore()
    store.record_tool_invocation(task_id, "datum_task_ui_review", "human")
    try:
        state = store.review(task_id, decision, note, initiator="human", evaluation_id=evaluation_id)
    except ValueError as exc:
        return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)
    return _result(task_interface.build_interface(state), "Local review recorded; no business authorization")


def register_apps(apps) -> None:
    apps.tool(name="datum_task_open", resource_uri=URI,
              description=datum_task_open.__doc__)(datum_task_open)
    apps.tool(name="datum_task_ui_evaluate", resource_uri=URI, visibility=["app"],
              description=datum_task_ui_evaluate.__doc__)(datum_task_ui_evaluate)
    apps.tool(name="datum_task_ui_review", resource_uri=URI, visibility=["app"],
              description=datum_task_ui_review.__doc__)(datum_task_ui_review)
    apps.add_html_resource(URI, Path(__file__).with_name("task_interface.html").read_text(encoding="utf-8"),
                           title="Datum — Persistent task investigation", prefers_border=True)


def register_tools(mcp) -> None:
    for fn in (datum_list_machines, datum_get_machine, datum_get_required_parts,
               datum_check_inventory, datum_find_alternatives, datum_compare_strategies):
        mcp.tool(name=fn.__name__, annotations=ToolAnnotations(readOnlyHint=True))(fn)
    for fn in (datum_task_create, datum_task_evaluate, datum_task_get):
        mcp.tool(name=fn.__name__, annotations=ToolAnnotations(readOnlyHint=False))(fn)

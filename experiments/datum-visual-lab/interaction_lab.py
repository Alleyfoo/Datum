"""Independent, read-only server-defined menu for the MCP Apps experiment.

Configuration is re-read for each call; it is data, never executable code.
Visibility is a host-facing hint, not an authorization mechanism.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from mcp.types import CallToolResult, TextContent, ToolAnnotations

MENU_PATH = Path(__file__).with_name("interaction_menu.json")
APP_URI = "ui://datum/interaction-lab"


def load_menu(path: Path | None = None) -> dict[str, Any]:
    data = json.loads((path or MENU_PATH).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("title"), str) or not isinstance(data.get("description"), str) or not isinstance(data.get("actions"), list):
        raise ValueError("Invalid interaction menu")
    seen: set[str] = set()
    for action in data["actions"]:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not action["id"] or not isinstance(action.get("label"), str) or not isinstance(action.get("enabled"), bool):
            raise ValueError("Invalid action")
        if action["id"] in seen:
            raise ValueError("Duplicate action id")
        seen.add(action["id"])
        result = action.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("heading"), str) or not isinstance(result.get("details"), list) or not all(isinstance(item, str) for item in result["details"]):
            raise ValueError("Invalid action result")
    return data


def public_menu() -> dict[str, Any]:
    data = load_menu()
    return {"kind": "menu", "title": data["title"], "description": data["description"], "actions": [{key: action[key] for key in ("id", "label", "enabled")} for action in data["actions"]]}


def run_action(action_id: str) -> dict[str, Any]:
    for action in load_menu()["actions"]:
        if action["id"] == action_id:
            if not action["enabled"]:
                raise ValueError("Action is disabled")
            return {"kind": "action_result", "action_id": action_id, "label": action["label"], **action["result"]}
    raise ValueError("Unknown action")


def register(apps: Any) -> None:
    def result(data: dict[str, Any]) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=f"Read-only interaction: {data['kind']}")], structured_content=data)

    @apps.tool(name="datum_open_interaction_lab", resource_uri=APP_URI,
               description="Open a read-only server-defined interaction menu containing synthetic data.",
               annotations=ToolAnnotations(readOnlyHint=True))
    def datum_open_interaction_lab() -> CallToolResult:
        return result(public_menu())

    @apps.tool(name="datum_menu_refresh", resource_uri=APP_URI, visibility=["app"],
               description="Reload the synthetic read-only menu for the interaction lab.",
               annotations=ToolAnnotations(readOnlyHint=True))
    def datum_menu_refresh() -> CallToolResult:
        return result(public_menu())

    @apps.tool(name="datum_menu_action", resource_uri=APP_URI, visibility=["app"],
               description="Fetch read-only synthetic details for one enabled menu action.",
               annotations=ToolAnnotations(readOnlyHint=True))
    def datum_menu_action(action_id: str) -> CallToolResult:
        return result(run_action(action_id))

    apps.add_html_resource(APP_URI, Path(__file__).with_name("interaction_lab.html").read_text(encoding="utf-8"),
                           title="Datum — Interaction Lab", prefers_border=True)


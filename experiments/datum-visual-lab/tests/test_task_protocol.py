"""Scripted protocol-level MCP experiment; this is not an autonomous agent run.

Run only against a disposable server/database, for example:
  $env:DATUM_HOST='http://127.0.0.1:8000/mcp'
  $env:DATUM_TASK_TEST_DATABASE_ISOLATED='1'
  python -m unittest discover -s tests -p test_task_protocol.py -v
No fixture is modified. Direct calls to app-only tools here test server/protocol
behavior, not host enforcement; test the reference host independently.
"""
from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HOST = os.environ.get("DATUM_HOST")
ISOLATED = os.environ.get("DATUM_TASK_TEST_DATABASE_ISOLATED") == "1"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def source_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FIXTURES.glob("*.csv"))}


@unittest.skipUnless(HOST and ISOLATED, "Set DATUM_HOST to the MCP endpoint and DATUM_TASK_TEST_DATABASE_ISOLATED=1 for a throwaway server database")
class TaskProtocolTests(unittest.TestCase):
    def test_scripted_mcp_handoff_and_renderer_contract(self):
        async def call(session, name, arguments):
            result = await session.call_tool(name, arguments)
            self.assertFalse(result.is_error, f"{name} failed: {result.content}")
            self.assertIsInstance(result.structured_content, dict, name)
            return result.structured_content

        async def rejected(session, name, arguments):
            result = await session.call_tool(name, arguments)
            self.assertTrue(result.is_error, f"{name} should reject {arguments!r}")

        async def run():
            before = source_hashes()
            async with streamable_http_client(HOST) as transport:
                async with ClientSession(transport[0], transport[1]) as session:
                    init = await session.initialize()
                    tools = {t.name: t for t in (await session.list_tools()).tools}
                    required = {"datum_list_machines", "datum_get_machine", "datum_get_required_parts", "datum_check_inventory",
                                "datum_find_alternatives", "datum_compare_strategies", "datum_task_create", "datum_task_evaluate",
                                "datum_task_get", "datum_task_open", "datum_task_ui_evaluate", "datum_task_ui_review"}
                    self.assertTrue(required <= tools.keys(), required - tools.keys())
                    self.assertIn("machine_id", tools["datum_get_machine"].input_schema["properties"])
                    self.assertIn("machine_id", tools["datum_get_machine"].input_schema.get("required", []))
                    self.assertEqual(tools["datum_task_ui_evaluate"].meta["ui"]["visibility"], ["app"])
                    self.assertEqual(tools["datum_task_ui_review"].meta["ui"]["visibility"], ["app"])
                    self.assertEqual(tools["datum_task_open"].meta["ui"]["resourceUri"], "ui://datum/task-experiment")
                    resource = await session.read_resource("ui://datum/task-experiment")
                    self.assertEqual(resource.contents[0].mime_type, "text/html;profile=mcp-app")

                    machines = await call(session, "datum_list_machines", {})
                    self.assertIn("BC-01", [m["id"] for m in machines["machines"]])
                    machine = await call(session, "datum_get_machine", {"machine_id": "BC-01"})
                    self.assertEqual(machine["id"], "BC-01")
                    bom = await call(session, "datum_get_required_parts", {"machine_id": "BC-01"})
                    part_ids = [part["part_id"] for part in bom["requirements"]]
                    self.assertEqual(set(part_ids), {"PL-40", "GBX-200"})
                    inventory = await call(session, "datum_check_inventory", {"part_ids": part_ids})
                    self.assertTrue(all(part["stock"] == 0 for part in inventory["parts"]))
                    alternative = await call(session, "datum_find_alternatives", {"part_id": "PL-40"})
                    self.assertEqual(alternative["finding"], "unknown")
                    compared = await call(session, "datum_compare_strategies", {"machine_id": "BC-01", "allow_substitutes": False})
                    self.assertEqual([x["conclusion"]["status"] for x in compared["results"]], ["blocked", "ready"])
                    self.assertEqual(compared["results"][0]["receipt"]["source_hashes"], compared["results"][1]["receipt"]["source_hashes"])

                    params = {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": False}
                    created = await call(session, "datum_task_create", {"task_type": "repair_investigation", **params,
                        "recommendation": "Investigate source evidence; this is not an approval.",
                        "next_steps": ["Ask a person to review evidence"]})
                    task_id = created["task_id"]
                    agent = await call(session, "datum_task_evaluate", {"task_id": task_id, **params})
                    first = agent["evaluations"][-1]["result"]
                    self.assertEqual(first["conclusion"]["status"], "blocked")
                    opening = await call(session, "datum_task_open", {"task_id": task_id})
                    self.assertEqual(opening["task_type"], "repair_investigation")
                    self.assertIn("evidence_graph", {c["type"] for c in opening["components"]})
                    app = await call(session, "datum_task_ui_evaluate", {"task_id": task_id, **params})
                    self.assertEqual(app["schema_version"], opening["schema_version"])
                    state = await call(session, "datum_task_get", {"task_id": task_id})
                    self.assertEqual(len(state["evaluations"]), 2)
                    self.assertEqual(first, state["evaluations"][-1]["result"])
                    self.assertEqual([x["initiator"] for x in state["evaluations"]], ["agent", "human"])
                    old_eval = state["evaluations"][-1]["evaluation_id"]
                    changed = {**params, "strategy": "delivery"}
                    await call(session, "datum_task_ui_evaluate", {"task_id": task_id, **changed})
                    state = await call(session, "datum_task_get", {"task_id": task_id})
                    self.assertEqual(len(state["evaluations"]), 3)
                    self.assertEqual(state["parameters"], changed)
                    self.assertEqual(state["current_result"]["conclusion"]["status"], "ready")
                    self.assertEqual(first, state["evaluations"][0]["result"])
                    await rejected(session, "datum_task_ui_review", {"task_id": task_id, "evaluation_id": old_eval,
                                                                      "decision": "reviewed", "note": "stale"})
                    current_eval = state["evaluations"][-1]["evaluation_id"]
                    await call(session, "datum_task_ui_review", {"task_id": task_id, "evaluation_id": current_eval,
                                                                 "decision": "needs_more_information", "note": "Confirm physical condition."})
                    state = await call(session, "datum_task_get", {"task_id": task_id})
                    self.assertEqual(state["reviews"][-1]["evaluation_id"], current_eval)
                    self.assertEqual(state["reviews"][-1]["decision"], "needs_more_information")
                    self.assertIn("unverified", state["identity_note"])
                    event_names = {e["event_type"] for e in state["events"]}
                    self.assertTrue({"task_created", "tool_invoked", "parameters_validated", "data_sources_accessed", "rule_applied",
                                     "evaluation_completed", "parameter_changed", "human_review_recorded", "task_reopened"} <= event_names)
                    await rejected(session, "datum_task_evaluate", {"task_id": task_id, **params, "strategy": "invalid"})
                    await rejected(session, "datum_task_open", {"task_id": task_id, "requested_components": ["arbitrary_javascript"]})
                    await rejected(session, "datum_get_machine", {"machine_id": "unknown"})
                    await rejected(session, "datum_task_create", {"task_type": "repair_investigation", **params, "allow_substitutes": "maybe"})
                    await rejected(session, "datum_task_create", {"task_type": "repair_investigation", **params, "allow_substitutes": "false"})
                    await rejected(session, "datum_task_evaluate", {"task_id": task_id, **params, "allow_substitutes": "false"})
                    await rejected(session, "datum_task_ui_evaluate", {"task_id": task_id, **params, "allow_substitutes": "false"})
                    await rejected(session, "datum_compare_strategies", {"machine_id": "BC-01", "allow_substitutes": "false"})

                    conflict = await call(session, "datum_task_create", {"task_type": "supplier_conflict_review", "part_id": "CP-09-ALT"})
                    await call(session, "datum_task_evaluate", {"task_id": conflict["task_id"], "part_id": "CP-09-ALT"})
                    conflict_ui = await call(session, "datum_task_open", {"task_id": conflict["task_id"]})
                    self.assertEqual(conflict_ui["schema_version"], opening["schema_version"])
                    self.assertNotIn("evidence_graph", {c["type"] for c in conflict_ui["components"]})
                    claims = conflict_ui["data"]["claims"]["rows"]
                    self.assertEqual({c["claim"] for c in claims}, {"Compatible", "Not compatible"})

            # A new transport and session demonstrate that the server retained the task.
            async with streamable_http_client(HOST) as transport:
                async with ClientSession(transport[0], transport[1]) as session:
                    await session.initialize()
                    recovered = await call(session, "datum_task_get", {"task_id": task_id})
                    reopened = await call(session, "datum_task_open", {"task_id": task_id})
                    self.assertEqual(recovered["parameters"], changed)
                    self.assertEqual(len(recovered["evaluations"]), 3)
                    self.assertEqual(recovered["reviews"][-1]["note"], "Confirm physical condition.")
                    self.assertEqual(reopened["task_id"], task_id)
            self.assertEqual(before, source_hashes(), "Synthetic source files changed during the test")
            print(f"Scripted MCP test passed; negotiated core {init.protocol_version}; task {task_id}; no model involved")

        anyio.run(run)


if __name__ == "__main__":
    unittest.main()

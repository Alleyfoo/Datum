"""Checks the same data-only renderer contract for both task types."""
import unittest
from unittest.mock import patch

import task_domain
import task_interface


class InterfaceTests(unittest.TestCase):
    def task(self, kind, parameters):
        result = task_domain.evaluate_task(kind, parameters)
        evaluation = {"evaluation_id": "eval-test", "created_at": "2026-10-27", "initiator": "agent",
                      "parameters": parameters, "result": result}
        return {"task_id": "task-test", "task_type": kind, "parameters": parameters,
                "current_result": result, "evaluations": [evaluation], "reviews": [],
                "recommendation": "Inspect the sources", "next_steps": ["Seek review"],
                "outstanding_questions": result["unresolved"]}

    def test_two_tasks_share_vocabulary_but_get_distinct_composition(self):
        repair = self.task("repair_investigation", {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": False})
        supplier = self.task("supplier_conflict_review", {"part_id": "CP-09-ALT"})
        a = task_interface.build_interface(repair)
        b = task_interface.build_interface(supplier)
        self.assertEqual(a["schema_version"], b["schema_version"])
        self.assertTrue(all(c["type"] in task_interface.COMPONENT_TYPES for c in a["components"] + b["components"]))
        self.assertIn("evidence_graph", [c["type"] for c in a["components"]])
        self.assertNotIn("evidence_graph", [c["type"] for c in b["components"]])
        self.assertEqual(a["data"]["requirements"]["rows"], repair["current_result"]["evidence"]["evaluation_machine"]["requirements"])
        self.assertEqual(b["data"]["claims"]["rows"], supplier["current_result"]["evidence"]["claims"])
        self.assertEqual(a["data"]["receipt"]["items"][0]["value"], repair["current_result"]["receipt"]["run_id"])
        self.assertEqual(a["data"]["review"]["action"]["arguments"]["evaluation_id"], "eval-test")

    def test_component_requests_are_validated_and_ordered(self):
        task = self.task("repair_investigation", {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": False})
        view = task_interface.build_interface(task, ["decision_receipt", "status_summary"])
        self.assertEqual([c["type"] for c in view["components"]], ["decision_receipt", "status_summary"])
        for invalid in (["script"], ["data_table", "data_table"], "data_table"):
            with self.assertRaises(ValueError):
                task_interface.build_interface(task, invalid)
        supplier = self.task("supplier_conflict_review", {"part_id": "CP-09-ALT"})
        with self.assertRaises(ValueError):
            task_interface.build_interface(supplier, ["evidence_graph"])

    def test_no_review_form_before_an_evaluation(self):
        task = self.task("repair_investigation", {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": False})
        task["current_result"] = None
        task["evaluations"] = []
        view = task_interface.build_interface(task)
        self.assertNotIn("review", view["data"])
        self.assertEqual(view["data"]["receipt"]["notes"], ["No evaluation has been recorded yet."])

    def test_saved_results_survive_unavailable_current_sources(self):
        for kind, parameters in (
            ("repair_investigation", {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": False}),
            ("supplier_conflict_review", {"part_id": "CP-09-ALT"}),
        ):
            with self.subTest(kind=kind):
                task = self.task(kind, parameters)
                with patch.object(task_interface.datum_engine, "load_fixture", side_effect=FileNotFoundError("missing fixture")):
                    view = task_interface.build_interface(task)
                self.assertFalse(view["data"]["parameters"]["action"]["enabled"])
                self.assertIn("unavailable", view["data"]["parameters"]["action"]["disabled_reason"])
                self.assertIn("saved evidence", view["data"]["status"]["notes"][0])
                self.assertEqual(view["data"]["receipt"]["items"][0]["value"], task["current_result"]["receipt"]["run_id"])
                self.assertEqual(len(view["data"]["history"]["rows"]), 1)
                self.assertNotEqual(view["data"]["review"]["action"].get("enabled"), False)


if __name__ == "__main__":
    unittest.main()

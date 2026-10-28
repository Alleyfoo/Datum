import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.sqlite"
        self.store = TaskStore(self.path)
        self.first = {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": False}
        self.second = {**self.first, "strategy": "delivery"}

    def result(self, params, run_id):
        return {
            "task_type": "repair_investigation", "parameters": params,
            "conclusion": {"status": "blocked"}, "evidence": [{"source": "bom.csv:2"}],
            "unresolved": ["Machine condition is unknown"],
            "receipt": {"run_id": run_id, "input_sha256": "input-hash", "source_hashes": {"bom.csv": "source-hash"}, "ruleset": "rule-1"},
        }

    def create(self):
        return self.store.create("repair_investigation", self.first, "agent", "Inspect the missing part", ["Ask a person to review"])

    def test_reopen_preserves_each_evaluation_receipt_and_review(self):
        task = self.create()
        tid = task["task_id"]
        self.store.record_tool_invocation(tid, "evaluate", "agent")
        a = self.store.evaluate(tid, self.first, self.result(self.first, "ONE"), "agent")
        self.store.evaluate(tid, self.second, self.result(self.second, "TWO"), "human")
        self.store.review(tid, "needs_more_information", "Check condition", "human")
        reopened = TaskStore(self.path).get(tid, reopen=True, initiator="agent")
        self.assertEqual(reopened["parameters"], self.second)
        self.assertEqual([x["result"]["receipt"]["run_id"] for x in reopened["evaluations"]], ["ONE", "TWO"])
        self.assertEqual(reopened["evaluations"][0]["result"], a["current_result"])
        self.assertEqual(reopened["reviews"][0]["evaluation_id"], reopened["evaluations"][1]["evaluation_id"])
        self.assertEqual(reopened["recommendation"], "Inspect the missing part")
        self.assertEqual(reopened["outstanding_questions"], ["Machine condition is unknown"])
        self.assertIn("unverified", reopened["identity_note"])
        kinds = [x["event_type"] for x in reopened["events"]]
        for expected in ("task_created", "tool_invoked", "parameters_validated", "parameter_changed", "data_sources_accessed", "rule_applied", "evaluation_completed", "human_review_recorded", "task_reopened"):
            self.assertIn(expected, kinds)
        review_event = next(e for e in reopened["events"] if e["event_type"] == "human_review_recorded")
        self.assertFalse(review_event["details"]["authorization"])

    def test_rejects_mismatched_result_without_partial_mutation(self):
        tid = self.create()["task_id"]
        before = self.store.get(tid)
        with self.assertRaisesRegex(ValueError, "evaluated parameters"):
            self.store.evaluate(tid, self.second, self.result(self.first, "ONE"), "human")
        wrong_type = self.result(self.first, "ONE")
        wrong_type["task_type"] = "supplier_conflict_review"
        with self.assertRaisesRegex(ValueError, "task type"):
            self.store.evaluate(tid, self.first, wrong_type, "human")
        after = self.store.get(tid)
        self.assertEqual(before, after)

    def test_reviews_are_not_approvals_and_require_existing_result(self):
        tid = self.create()["task_id"]
        with self.assertRaisesRegex(ValueError, "requires an evaluation"):
            self.store.review(tid, "reviewed", "", "human")
        self.store.evaluate(tid, self.first, self.result(self.first, "ONE"), "agent")
        for decision, actor in (("approve", "human"), ("reviewed", "agent")):
            with self.assertRaises(ValueError):
                self.store.review(tid, decision, "", actor)

    def test_stale_review_is_rejected_instead_of_attaching_to_newer_evidence(self):
        tid = self.create()["task_id"]
        first = self.store.evaluate(tid, self.first, self.result(self.first, "ONE"), "agent")
        displayed = first["evaluations"][-1]["evaluation_id"]
        latest = self.store.evaluate(tid, self.second, self.result(self.second, "TWO"), "human")
        with self.assertRaisesRegex(ValueError, "reopen"):
            self.store.review(tid, "reviewed", "Old result", "human", evaluation_id=displayed)
        self.assertEqual(self.store.get(tid)["reviews"], [])
        newest = latest["evaluations"][-1]["evaluation_id"]
        saved = self.store.review(tid, "reviewed", "Current result", "human", evaluation_id=newest)
        self.assertEqual(saved["reviews"][0]["evaluation_id"], newest)

    def test_invalid_ids_receipts_and_nonfinite_values_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.get("not-a-task")
        tid = self.create()["task_id"]
        bad = self.result(self.first, "ONE")
        del bad["receipt"]["ruleset"]
        with self.assertRaisesRegex(ValueError, "receipt"):
            self.store.evaluate(tid, self.first, bad, "agent")
        bad = self.result(self.first, "ONE")
        bad["evidence"] = [float("nan")]
        with self.assertRaises(ValueError):
            self.store.evaluate(tid, self.first, bad, "agent")
        self.assertEqual(self.store.get(tid)["evaluations"], [])

    def test_conflict_tasks_are_independent_and_persistent(self):
        task = self.store.create("supplier_conflict_review", {"part_id": "CP-09-ALT"}, "human")
        self.assertEqual(TaskStore(self.path).get(task["task_id"])["task_type"], "supplier_conflict_review")
        self.assertNotEqual(task["task_id"], self.create()["task_id"])

    def test_concurrent_evaluations_preserve_history_and_change_chain(self):
        tid = self.create()["task_id"]
        params_list = [{**self.first, "run": i} for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda pair: self.store.evaluate(tid, pair[1], self.result(pair[1], str(pair[0])), "agent"), enumerate(params_list)))
        saved = self.store.get(tid)
        self.assertEqual(len(saved["evaluations"]), 4)
        self.assertEqual({x["result"]["receipt"]["run_id"] for x in saved["evaluations"]}, {"0", "1", "2", "3"})
        changes = [e["details"] for e in saved["events"] if e["event_type"] == "parameter_changed"]
        self.assertEqual(len(changes), 4)
        previous = self.first
        for change in changes:
            self.assertEqual(change["before"], previous)
            previous = change["after"]
        self.assertEqual(saved["parameters"], previous)

    def test_real_domain_result_survives_persistence_without_recomputation(self):
        from task_domain import evaluate_task
        tid = self.create()["task_id"]
        result = evaluate_task("repair_investigation", self.first)
        self.store.evaluate(tid, self.first, result, "agent")
        saved = TaskStore(self.path).get(tid, reopen=True, initiator="human")
        self.assertEqual(saved["current_result"], result)
        self.assertEqual(saved["outstanding_questions"], result["unresolved"])
        self.assertEqual(saved["evaluations"][0]["result"]["receipt"]["source_hashes"], result["receipt"]["source_hashes"])


if __name__ == "__main__":
    unittest.main()

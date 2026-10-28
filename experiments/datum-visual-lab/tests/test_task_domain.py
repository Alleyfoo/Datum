"""Behavioral checks for shared, snapshot-based task operations."""
import copy
import hashlib
import unittest

import datum_engine as engine
import task_domain as domain


class TaskDomainTests(unittest.TestCase):
    def setUp(self):
        self.sources = engine.capture_sources()

    def test_machine_requirements_inventory_and_unknown_alternatives(self):
        machine = domain.get_machine("BC-01", self.sources)
        self.assertEqual(machine["source"], "machines.csv:2")
        requirements = domain.get_required_parts("BC-01", self.sources)
        self.assertEqual({p["part_id"] for p in requirements["requirements"]}, {"PL-40", "GBX-200"})
        stock = domain.check_inventory(["PL-40", "GBX-200"], self.sources)
        self.assertEqual([p["stock"] for p in stock["parts"]], [0, 0])
        self.assertEqual(domain.find_alternatives("PL-40", self.sources)["finding"], "unknown")
        self.assertFalse(domain.get_required_parts("BE-01", self.sources)["known"])

    def test_claims_are_evidence_not_substitution(self):
        claims = domain.find_alternatives("CP-09", self.sources)
        self.assertEqual({c["claim"] for c in claims["claim_records"]}, {"Compatible", "Not compatible"})
        self.assertEqual([c["record_source"] for c in claims["claim_records"]], ["claims.csv:2", "claims.csv:3"])
        result = domain.evaluate_task("supplier_conflict_review", {"part_id": "CP-09-ALT"}, self.sources)
        self.assertTrue(result["conclusion"]["conflicting_claims"])
        self.assertEqual(result["conclusion"]["status"], "review")
        self.assertTrue(all(not c["accepted"] for c in result["evidence"]["claims"]))

    def test_repair_determinism_strategy_comparison_and_no_assumed_substitution(self):
        params = {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": True}
        first = domain.evaluate_task("repair_investigation", params, self.sources)
        self.assertEqual(first, domain.evaluate_task("repair_investigation", copy.deepcopy(params), self.sources))
        self.assertEqual(first["conclusion"]["status"], "blocked")
        self.assertFalse(first["conclusion"]["substitution_applied"])
        self.assertEqual([a["finding"] for a in first["alternatives"]], ["unknown", "unknown"])
        compared = domain.compare_strategies("BC-01", False, self.sources)["results"]
        self.assertEqual([x["conclusion"]["status"] for x in compared], ["blocked", "ready"])
        self.assertEqual(compared[0]["receipt"]["source_hashes"], compared[1]["receipt"]["source_hashes"])

    def test_receipt_uses_captured_source_bytes_even_after_new_snapshot_changes(self):
        params = {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": False}
        before = domain.evaluate_task("repair_investigation", params, self.sources)
        changed = dict(self.sources)
        changed["stock.csv"] = changed["stock.csv"].replace(b"PL-40,Drive pulley,0,70", b"PL-40,Drive pulley,1,70")
        self.assertNotEqual(changed["stock.csv"], self.sources["stock.csv"])
        after = domain.evaluate_task("repair_investigation", params, changed)
        self.assertEqual(before["receipt"]["source_hashes"]["stock.csv"], hashlib.sha256(self.sources["stock.csv"]).hexdigest())
        self.assertEqual(after["receipt"]["source_hashes"]["stock.csv"], hashlib.sha256(changed["stock.csv"]).hexdigest())
        self.assertNotEqual(before["receipt"]["run_id"], after["receipt"]["run_id"])
        self.assertEqual(before, domain.evaluate_task("repair_investigation", params, self.sources))

    def test_invalid_inputs_rejected(self):
        for call in (lambda: domain.get_machine("NO-SUCH-MACHINE", self.sources),
                     lambda: domain.check_inventory(["NO-SUCH-PART"], self.sources),
                     lambda: domain.find_alternatives("", self.sources),
                     lambda: domain.evaluate_task("repair_investigation", {"machine_id": "BC-01", "strategy": "actual", "allow_substitutes": False}, self.sources),
                     lambda: domain.evaluate_task("repair_investigation", {"machine_id": "BC-01", "strategy": "baseline", "allow_substitutes": "yes"}, self.sources),
                     lambda: domain.evaluate_task("supplier_conflict_review", {"part_id": "CP-09-ALT", "extra": 1}, self.sources)):
            with self.assertRaises(ValueError):
                call()


if __name__ == "__main__":
    unittest.main()

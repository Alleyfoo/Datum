"""Checks for the synthetic business cases and a changed source record."""
import csv
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import datum_engine


class BusinessCaseTests(unittest.TestCase):
    def test_invalid_duplicate_and_unknown_records_are_rejected(self):
        originals = {name: datum_engine._csv_rows(name) for name in
                     ("machines.csv", "bom.csv", "stock.csv", "claims.csv")}
        cases = [
            ("machines.csv", dict(originals["machines.csv"][0]), "Duplicate machine ID"),
            ("bom.csv", dict(originals["bom.csv"][0]), "Duplicate BOM entry"),
            ("stock.csv", dict(originals["stock.csv"][0]), "Duplicate part ID"),
            ("bom.csv", {"machine_id": "BC-01", "part_id": "UNKNOWN", "required": "1"}, "Unknown stock part"),
        ]
        for filename, row, message in cases:
            with self.subTest(filename=filename, message=message):
                rows = {name: list(value) for name, value in originals.items()}
                rows[filename].append(row)
                with patch.object(datum_engine, "_csv_rows", side_effect=lambda name: rows[name]):
                    with self.assertRaisesRegex(ValueError, message):
                        datum_engine.evaluate()

    def test_missing_bom_and_two_missing_parts_have_evidence(self):
        result = datum_engine.evaluate("baseline")
        machines = {m["id"]: m for m in result["machines"]}
        self.assertEqual(machines["BE-01"]["status"], "review")
        self.assertTrue(machines["BE-01"]["missing_bom"])
        self.assertIsNone(machines["BE-01"]["bom_source"])
        conveyor = machines["BC-01"]
        self.assertEqual(conveyor["status"], "blocked")
        self.assertEqual({r["part"] for r in conveyor["requirements"]}, {"PL-40", "GBX-200"})
        self.assertTrue(all(r["available_before"] == 0 for r in conveyor["requirements"]))

    def test_competing_bearing_allocation_is_conserved(self):
        result = datum_engine.evaluate("delivery")
        machines = {m["id"]: m for m in result["machines"]}
        bearing = next(s for s in result["stock"] if s["id"] == "BRG-6208")
        self.assertEqual(machines["CR-01"]["allocated"], [{"machine": "CR-01", "part": "BRG-6208", "quantity": 1}])
        self.assertEqual(machines["PK-01"]["allocated"], [])
        self.assertEqual(bearing["stock"], 1)
        self.assertEqual(bearing["remaining"], 0)
        self.assertEqual(next(r for r in machines["PK-01"]["requirements"] if r["part"] == "BRG-6208")["available_before"], 0)

    def test_conflicting_claims_remain_unaccepted_and_linked(self):
        result = datum_engine.evaluate("baseline")
        claims = result["claims"]
        self.assertEqual({c["claim"] for c in claims}, {"Compatible", "Not compatible"})
        self.assertTrue(all(c["part"] == "CP-09-ALT" and not c["accepted"] for c in claims))
        machine = next(m for m in result["machines"] if m["id"] == "CF-01")
        self.assertEqual(machine["status"], "review")
        self.assertTrue(machine["has_conflict"])

    def test_quarantine_preserves_bad_value_and_does_not_allocate_it(self):
        baseline = datum_engine.evaluate("baseline")
        result = datum_engine.evaluate("quarantine")
        self.assertEqual(result["quarantined"][0]["raw_quantity"], "1?")
        self.assertEqual(result["quarantined"][0]["part"], "BRG-6208")
        self.assertEqual(result["stock"], baseline["stock"])
        self.assertEqual(result["machines"], baseline["machines"])

    def test_changed_csv_is_read_by_next_evaluation(self):
        # Work on a disposable copy, preserving the checked-in synthetic records.
        fixture = datum_engine.FIXTURE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)
            for source in fixture.glob("*.csv"):
                shutil.copy(source, copy / source.name)
            with patch.object(datum_engine, "FIXTURE_DIR", copy):
                before = datum_engine.evaluate("baseline")
                path = copy / "stock.csv"
                with path.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                next(row for row in rows if row["part_id"] == "BRG-6208")["quantity"] = "1"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                after = datum_engine.evaluate("baseline")
        before_machines = {m["id"]: m for m in before["machines"]}
        after_machines = {m["id"]: m for m in after["machines"]}
        self.assertEqual(before_machines["CR-01"]["status"], "blocked")
        self.assertEqual(after_machines["CR-01"]["status"], "ready")
        self.assertEqual(after_machines["PK-01"]["status"], "blocked")
        self.assertNotEqual(before["receipt"]["source_hashes"]["stock.csv"], after["receipt"]["source_hashes"]["stock.csv"])
        self.assertNotEqual(before["receipt"]["input_sha256"], after["receipt"]["input_sha256"])

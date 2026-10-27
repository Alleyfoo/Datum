"""Run with: python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datum_engine import evaluate, source_hashes, text_summary, load_fixture


class DatumEngineTests(unittest.TestCase):
    def test_baseline_statuses(self):
        x = evaluate('baseline')
        self.assertEqual(x['counts'], {'ready': 3, 'blocked': 3, 'review': 3})
        by_id = {m['id']: m for m in x['machines']}
        self.assertEqual(by_id['BC-01']['status'], 'blocked')
        self.assertEqual(by_id['BE-01']['status'], 'review')
        self.assertEqual(by_id['CF-01']['status'], 'review')

    def test_shared_stock_cannot_be_used_twice(self):
        x = evaluate('delivery')
        self.assertEqual(x['counts'], {'ready': 5, 'blocked': 1, 'review': 3})
        by_id = {m['id']: m for m in x['machines']}
        self.assertEqual(by_id['CR-01']['status'], 'ready')
        self.assertEqual(by_id['PK-01']['status'], 'blocked')
        bearing = next(p for p in x['stock'] if p['id'] == 'BRG-6208')
        self.assertEqual(bearing['remaining'], 0)
        self.assertIn('CR-01', by_id['PK-01']['reasons'][0])

    def test_quarantined_record_does_not_become_stock(self):
        base, bad = evaluate('baseline'), evaluate('quarantine')
        self.assertEqual(base['counts'], bad['counts'])
        self.assertEqual(len(bad['quarantined']), 1)
        self.assertEqual(next(p for p in bad['stock'] if p['id'] == 'BRG-6208')['stock'], 0)

    def test_conflicting_substitution_never_auto_accepts(self):
        x = evaluate('delivery')
        self.assertEqual(next(m for m in x['machines'] if m['id'] == 'CF-01')['status'], 'review')
        self.assertEqual({c['claim'] for c in x['claims']}, {'Compatible', 'Not compatible'})

    def test_actual_csv_hashes_and_stable_receipt(self):
        hashes = source_hashes()
        self.assertEqual(set(hashes), {'bom.csv', 'claims.csv', 'machines.csv', 'stock.csv'})
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))
        self.assertEqual(evaluate('baseline')['receipt']['source_hashes'], hashes)
        self.assertEqual(evaluate('baseline')['receipt']['run_id'], evaluate('baseline')['receipt']['run_id'])

    def test_bom_known_but_missing_stock_does_not_pass(self):
        self.assertEqual(len(load_fixture()[0]), 9)
        self.assertIn('No write-back', text_summary())


if __name__ == '__main__':
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harden.experiments.compiler_pilot import run_pilot


class CompilerPilotTests(unittest.TestCase):
    def test_measured_results_provenance_and_independent_transfers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch('harden.experiments.compiler_pilot.ROOT', root):
                result = run_pilot(['arith_compute', 'clue_guess_easy', 'trading_sim'],
                    run_id='test', samples=5, seed=7, output=root / 'evidence')
            self.assertEqual((result['N'], result['M'], result['attempts']), (3, 3, 15))
            self.assertEqual(result['confirmed_cases'], 15)
            self.assertEqual(result['blocked_cases'], 15)
            self.assertEqual(result['benign_passed'], 15)
            self.assertIn('scripted', result['provenance'])
            batch = json.loads((root / 'evidence' / 'batch.json').read_text())
            self.assertEqual(len(batch['applications']), 2)
            for app in batch['applications']:
                self.assertNotEqual(app['target_env_id'], batch['entries'][0]['env_id'])
                self.assertEqual(app['outcome'], 'blocked')
            for entry in batch['entries']:
                report = json.loads((root / entry['invariant']['evidence_path']).read_text())
                self.assertTrue(all(not c['strict_correct'] for c in report['cases']))
                self.assertEqual(entry['embedding'], [])

    def test_invalid_scope_rejected_without_experiment(self):
        for run_id, samples in [('../bad', 1), ('ok', 0), ('ok', 1001)]:
            with self.assertRaises(ValueError):
                run_pilot(['arith_compute'], run_id=run_id, samples=samples, seed=0, output=Path('/tmp/unused'))

    def test_no_findings_in_first_game_never_produce_self_transfer(self):
        from env_compiler.loader import load_game
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def load(ref, strict):
                return load_game(ref, strict=True if ref == 'arith_compute' else strict)
            with patch('harden.experiments.compiler_pilot.ROOT', root), patch('harden.experiments.compiler_pilot.load_game', side_effect=load):
                result = run_pilot(['arith_compute', 'clue_guess_easy', 'trading_sim'],
                    run_id='partial', samples=2, seed=7, output=root / 'evidence')
            batch = json.loads((root / 'evidence/batch.json').read_text())
            self.assertEqual(result['M'], 2)
            self.assertEqual(len(batch['applications']), 1)
            self.assertNotEqual(batch['applications'][0]['target_env_id'], batch['entries'][0]['env_id'])

if __name__ == '__main__':
    unittest.main()

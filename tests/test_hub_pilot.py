import unittest
from pathlib import Path
from harden.experiments.hub_pilot import plan, DEFAULT_ENVS

ROOT = Path(__file__).resolve().parents[1]

class HubPilotPlanTests(unittest.TestCase):
    def test_plan_reports_missing_coordinator_without_promising_exploits(self):
        result = plan(ROOT, DEFAULT_ENVS)
        self.assertEqual(result['N'], 3)
        self.assertIsNone(result['M'])
        self.assertEqual(result['paid_budget_authorized_usd'], 0)
        self.assertEqual(result['model_calls_made'], 0)
        self.assertIsInstance(result['runner_verification_implemented'], bool)
        self.assertIsInstance(result['runner_entrypoint_implemented'], bool)
        self.assertEqual(len(result['environments']), 3)

    def test_known_failed_load_is_not_silently_added_to_pilot(self):
        with self.assertRaisesRegex(ValueError, 'data files'):
            plan(ROOT, ['ob1/base64bench'])
        with self.assertRaises(ValueError): plan(ROOT, [DEFAULT_ENVS[0], DEFAULT_ENVS[0]])
        with self.assertRaises(ValueError): plan(ROOT, DEFAULT_ENVS, 6)

if __name__ == '__main__':
    unittest.main()

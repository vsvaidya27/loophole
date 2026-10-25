import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from harden.audit.llm import BudgetExceeded, Claude, Ledger, MODEL

class Messages:
    def __init__(self, error=None): self.calls=[]; self.error=error
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error: raise self.error
        return SimpleNamespace(model=MODEL, usage=SimpleNamespace(input_tokens=100,output_tokens=20),
            content=[SimpleNamespace(type='text',text='{"ok":true}')],stop_reason='end_turn')

class BudgetTests(unittest.TestCase):
    def test_atomic_shared_reservations_never_pass_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'ledger',0.10)
            def reserve(_):
                try: return ledger.reserve(0.04,'test')
                except BudgetExceeded: return None
            with ThreadPoolExecutor(max_workers=8) as pool: ids=list(pool.map(reserve,range(8)))
            self.assertEqual(sum(bool(i) for i in ids),2)
            self.assertAlmostEqual(ledger.total(),0.08)

    def test_haiku_only_output_bound_and_settlement(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'AUDIT_HARD_CAP_USD':'','ANTHROPIC_MODEL':MODEL}):
            root=Path(folder); messages=Messages()
            client=Claude(root,root/'calls','compiler',client=SimpleNamespace(messages=messages))
            result=client.call(role='test',iteration=0,system='system',messages=[],max_tokens=24000,schema={})
            self.assertTrue(result.ok)
            self.assertEqual(messages.calls[0]['model'],MODEL)
            self.assertEqual(messages.calls[0]['max_tokens'],6000)
            self.assertNotIn('fallbacks',messages.calls[0])
            self.assertAlmostEqual(client.ledger.total(),result.cost_usd)
            self.assertLess(result.cost_usd,0.001)

    def test_timeout_keeps_reservation_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'AUDIT_HARD_CAP_USD':'','ANTHROPIC_MODEL':MODEL}):
            root=Path(folder); messages=Messages(TimeoutError('uncertain'))
            client=Claude(root,root/'calls','hacker',client=SimpleNamespace(messages=messages))
            with self.assertRaises(TimeoutError): client.call(role='test',iteration=0,system='x',messages=[])
            self.assertEqual(len(messages.calls),1)
            self.assertGreater(client.ledger.total(),0)

    def test_soft_warning_does_not_stop_spend_above_two_dollars(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {
                'AUDIT_HARD_CAP_USD':'', 'AUDIT_BUDGET_WARNING_USD':'2', 'ANTHROPIC_MODEL':MODEL}):
            root=Path(folder); messages=Messages()
            client=Claude(root,root/'calls','x',client=SimpleNamespace(messages=messages))
            client.ledger.record({'cost_usd':2.01,'env_id':'prior'})
            with self.assertWarnsRegex(RuntimeWarning,'continuing'):
                result=client.call(role='test',iteration=0,system='x',messages=[],schema={})
            self.assertTrue(result.ok)
            self.assertGreater(client.ledger.total(),2)
            self.assertEqual(client.remaining(),float('inf'))

    def test_overkill_model_is_not_selected(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {
                'AUDIT_HARD_CAP_USD':'', 'ANTHROPIC_MODEL':'claude-opus-5-5'}):
            with self.assertRaises(ValueError): Claude(Path(folder),Path(folder)/'calls','x')

    def test_missing_key_cannot_reserve_or_call(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'AUDIT_HARD_CAP_USD':'','ANTHROPIC_MODEL':MODEL,'ANTHROPIC_API_KEY':''}):
            root=Path(folder); client=Claude(root,root/'calls','x')
            with self.assertRaisesRegex(ValueError,'ANTHROPIC_API_KEY'): client.call(role='test',iteration=0,system='',messages=[])
            self.assertEqual(client.ledger.total(),0)

    def test_per_environment_cap_includes_other_client_reservations(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'ledger')
            ledger.reserve(0.07,'same',0.1)
            with self.assertRaises(BudgetExceeded): ledger.reserve(0.04,'same',0.1)
            self.assertIsNotNone(ledger.reserve(0.04,'other',0.1))

if __name__=='__main__': unittest.main()

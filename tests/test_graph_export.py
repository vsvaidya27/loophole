import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from harden.store import mirror
from harden.store.export import ExportError, build_batch
from harden.store.service_client import ServiceClient


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'invariants.db'
        self.env, self.exploit = 'test/env', 'one'
        self.replay = 'results/evidence/test/env/replays/one.json'
        target = self.root / self.replay
        target.parent.mkdir(parents=True)
        target.write_text('{}')
        (target.parent.parent / 'runtime.json').write_text('{"patch": "patches/test/env/patch.py"}')
        source = self.root / 'patches/test/env/patch.py'
        source.parent.mkdir(parents=True)
        source.write_text('def load_patched(): pass\n')
        self.exploit_class = sorted(mirror.EXPLOIT_CLASSES)[0]
        mirror.record_environment(self.env, source='hub', title=self.env, status='patched', db=self.db)
        mirror.record_exploit(self.env, self.exploit, exploit_class=self.exploit_class, iteration=1,
                              summary='An ambiguous final answer', sample_completion='wrong final answer',
                              reward_original=1.0, evidence_path=self.replay, db=self.db)
        mirror.mark_exploit_patched(self.env, self.exploit, reward_patched=0.0, db=self.db)
        mirror.record_invariant(mirror.Invariant(self.env, self.exploit, 'One answer only',
            'Ambiguous final answer accepted.', 'Only one fragment is parsed.',
            'Grader extracts one fragment.', 'Compare a single final answer.', self.replay), db=self.db)
        self.entry = {'env_id':self.env, 'status':'patched', 'evidence_dir':'results/evidence/test/env',
                      'exploits':[{'exploit_id':self.exploit,'exploit_class':self.exploit_class,'replay':'replays/one.json'}]}
        (self.root / 'results/leaderboard.json').write_text(json.dumps({'entries':[self.entry]}))

    def test_export_flows_through_service_client_and_preserves_fix_provenance(self):
        batch = build_batch(self.root)
        calls = []
        def send(request, **kwargs):
            calls.append((request.full_url.rsplit('/',1)[-1], json.loads(request.data)))
            return io.BytesIO(b'')
        with patch('harden.store.service_client.urlopen', send):
            ServiceClient('https://example.invalid', 'graph', 'test-token').push(batch)
        self.assertEqual([c[0] for c in calls], ['record_environment','record_exploit','record_invariant','graph_on_invariant','mark_exploit_patched'])
        self.assertEqual(calls[-1][1], [self.env,self.exploit,0.0])
        self.assertEqual(batch['entries'][0]['invariant']['evidence_path'], self.replay)
        self.assertEqual(len(batch['audit']['fixes'][0]['sha256']), 64)
        self.assertIsNone(mirror.invariant_rows(self.env, db=self.db)[0]['pushed_at'])

    def test_missing_invariant_fails_instead_of_exporting_incomplete_graph(self):
        with sqlite3.connect(self.db) as con:
            con.execute('DELETE FROM invariants')
        with self.assertRaises(ExportError):
            build_batch(self.root)

    def test_mismatched_evidence_is_rejected(self):
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE invariants SET evidence_path='other.json'")
        with self.assertRaises(ExportError):
            build_batch(self.root)


if __name__ == '__main__':
    unittest.main()

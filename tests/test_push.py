import json
import tempfile
import unittest
from pathlib import Path
from harden.store import mirror
from harden.store.push import push_once

class Client:
    def __init__(self): self.calls=[]; self.fail=None; self.hook=None
    def call(self,reducer,**fields):
        self.calls.append((reducer,fields))
        if self.hook: self.hook(reducer,fields)
        if self.fail==reducer: raise OSError('offline')

class PushTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Path(self.tmp.name)/'mirror.db'; self.client=Client()
        mirror.record_environment('hub/a',source='hub',title='A',status='running',db=self.db)
        mirror.record_exploit('hub/a','e1',exploit_class='multi-answer',iteration=1,summary='A confirmed failure',sample_completion='several answers',reward_original=1,evidence_path='evidence/a.json',db=self.db)
        mirror.record_invariant(mirror.Invariant('hub/a','e1','Exact answer','Multiple answers get full credit','Candidate aggregation is overly broad','A grader accepts multiple candidates','Require one valid final answer','evidence/a.json'),db=self.db)
    def tearDown(self): self.tmp.cleanup()
    def test_order_and_no_network_for_unchanged_rows(self):
        self.assertEqual(push_once(self.db,self.client)['errors'],0)
        self.assertEqual([name for name,_ in self.client.calls],['record_environment','record_exploit','record_invariant','graph_on_invariant'])
        self.client.calls.clear(); self.assertEqual(push_once(self.db,self.client),{'pushed':0,'errors':0})
        self.assertEqual(self.client.calls,[])
    def test_failed_graph_notification_keeps_invariant_pending(self):
        self.client.fail='graph_on_invariant'; self.assertEqual(push_once(self.db,self.client)['errors'],1)
        with mirror.connect(self.db) as con: row=con.execute('SELECT pushed_at,push_error FROM invariants').fetchone()
        self.assertIsNone(row[0]); self.assertIn('offline',row[1])
        self.client.fail=None; self.assertEqual(push_once(self.db,self.client)['pushed'],1)
    def test_concurrent_update_is_not_acknowledged(self):
        def hook(name,row):
            if name=='record_environment':
                mirror.record_environment('hub/a',source='hub',title='New title',status='running',db=self.db)
        self.client.hook=hook; push_once(self.db,self.client)
        with mirror.connect(self.db) as con: row=con.execute('SELECT title,pushed_at FROM environments').fetchone()
        self.assertEqual(row,('New title',None))
    def test_reset_rebuilds_remote_graph_before_new_rows(self):
        mirror.clear_environment('hub/a',db=self.db); push_once(self.db,self.client)
        self.assertEqual([n for n,_ in self.client.calls[:2]],['clear_environment','rebuild_graph'])
    def test_embedding_is_saved_once_and_reused_on_retry(self):
        calls=[]
        def embed(row): calls.append(row); return 'test-model',[1.0]+[0.0]*383
        self.client.fail='graph_on_invariant'; push_once(self.db,self.client,embed)
        self.client.fail=None; push_once(self.db,self.client,embed)
        self.assertEqual(len(calls),1)

if __name__=='__main__': unittest.main()

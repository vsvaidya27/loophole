import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from harden.store.retrieval import (COLUMNS, GraphRetriever, KnowledgeSnapshot,
                                    SQLiteKnowledgeSource, SpacetimeKnowledgeSource, prompt_context)
from harden.store.knowledge_loop import (FixProposal, KnowledgeClient, ReplayResult,
                                       propose_fix, validate_transfer, run_knowledge_transfer)


def snapshot():
    def inv(key, env, title):
        return dict(invariant_id=key, env_id=env, exploit_class='substring-match', title=title,
                    mechanism=title, preconditions=title, defense_pattern='Require one exact answer',
                    sample_completion='SECRET_EXPLOIT', evidence_path='SECRET_PATH')
    return KnowledgeSnapshot(
        tuple(dict(env_id=env, source=source) for env, source in
              [('hub/a', 'hub'), ('hub/b', 'hub'), ('seed/c', 'seed'), ('game/target', 'game')]),
        (inv('a', 'hub/a', 'substring parser'), inv('b', 'hub/b', 'ambiguous grading'),
         inv('s', 'seed/c', 'substring parser'), inv('t', 'game/target', 'substring parser')),
        ({'a_id': 'a', 'b_id': 'b', 'score': 0.9},))


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls, self.requests = reply, 0, []

    def complete(self, system, messages, max_tokens):
        self.calls += 1
        self.requests.append((system, messages, max_tokens))
        return self.reply


def replay(**changes):
    return replace(ReplayResult(1, 0, 1, 1, 3, 3, 'target attack'), **changes)


class RetrievalTests(unittest.TestCase):
    def retrieve(self, data=None, **kwargs):
        return GraphRetriever(data or snapshot()).retrieve('substring parser', '', target_env_id='game/target', **kwargs)

    def test_graph_expands_candidates_with_provenance(self):
        found = self.retrieve()
        self.assertEqual([m.invariant_id for m in found], ['a', 'b'])
        self.assertGreater(found[1].score, 0)
        self.assertIn('graph neighbour', found[1].reasons[0])
        without = self.retrieve(replace(snapshot(), similarity_edges=()))
        self.assertEqual(without[1].score, 0)

    def test_seed_target_and_missing_env_excluded(self):
        data = snapshot()
        data = replace(data, invariants=(*data.invariants, dict(data.invariants[0], invariant_id='ghost', env_id='missing')))
        self.assertEqual({m.invariant_id for m in self.retrieve(data)}, {'a', 'b'})

    def test_seed_and_target_cannot_anchor_graph(self):
        data = replace(snapshot(), similarity_edges=({'a_id': 's', 'b_id': 'b', 'score': 1},))
        self.assertEqual(self.retrieve(data)[1].score, 0)

    def test_invalid_edges_ignored(self):
        for weight in [float('nan'), float('inf'), -1, 2, 'bad']:
            with self.subTest(weight=weight):
                data = replace(snapshot(), similarity_edges=({'a_id': 'a', 'b_id': 'b', 'score': weight},))
                self.assertEqual(self.retrieve(data)[1].score, 0)

    def test_deterministic_order_and_limits(self):
        data = snapshot()
        self.assertEqual(self.retrieve(), self.retrieve(replace(data, invariants=tuple(reversed(data.invariants)))))
        self.assertEqual(len(self.retrieve(k=1)), 1)
        self.assertEqual(self.retrieve(k=0), [])
        for k in [-1, 101, True, 1.5]:
            with self.assertRaises(ValueError): self.retrieve(k=k)

    def test_missing_text_is_not_offered(self):
        data = replace(snapshot(), invariants=(dict(snapshot().invariants[0], preconditions=None),))
        self.assertEqual(self.retrieve(data), [])

    def test_prompt_is_bounded_and_contains_no_raw_evidence(self):
        context, ids = prompt_context(self.retrieve())
        self.assertEqual(ids, ('a', 'b'))
        self.assertNotIn('SECRET', context)
        context, ids = prompt_context(self.retrieve(), max_chars=2)
        self.assertEqual((context, ids), ('[]', ()))

    def test_http_columns_body_token_and_sql_decoding(self):
        data = snapshot()
        tables = (data.environments, data.invariants, data.similarity_edges)
        response = [{'schema': {'elements': [{'name': {'some': col}} for col in cols]},
                     'rows': [[r[col] for col in cols] for r in rows]}
                    for cols, rows in zip(COLUMNS.values(), tables)]
        with patch('harden.store.retrieval.urlopen', side_effect=[io.BytesIO(json.dumps([result]).encode()) for result in response]) as open_url:
            loaded = SpacetimeKnowledgeSource(database='space/name', token='test-token').load()
        request = open_url.call_args.args[0]
        self.assertEqual(open_url.call_count, 3)
        for invocation in open_url.call_args_list:
            self.assertNotIn(';', invocation.args[0].data.decode())
        self.assertIn('space%2Fname/sql', request.full_url)
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-token')
        self.assertNotIn('sample_completion', request.data.decode())
        self.assertNotIn('invariant_embedding', request.data.decode())
        self.assertEqual(loaded.source, 'spacetimedb')
        self.assertEqual(self.retrieve(loaded), self.retrieve())

    def test_http_failure_is_not_silently_empty(self):
        with patch('harden.store.retrieval.urlopen', side_effect=TimeoutError('offline')):
            with self.assertRaises(TimeoutError): SpacetimeKnowledgeSource().load()
        with patch('harden.store.retrieval.urlopen', return_value=io.BytesIO(b'[]')):
            with self.assertRaises(ValueError): SpacetimeKnowledgeSource().load()

    def test_current_audit_writer_records_are_retrievable(self):
        from harden.store import mirror
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mirror.db'
            mirror.record_environment('hub/real-writer', source='hub', title='Writer test', status='unpatched', db=path)
            mirror.record_exploit('hub/real-writer', 'e1', exploit_class='substring-match', iteration=1,
                summary='Substring parser', sample_completion='SECRET_EXPLOIT', reward_original=1,
                evidence_path='SECRET_PATH', db=path)
            mirror.record_invariant(mirror.Invariant(env_id='hub/real-writer', exploit_id='e1',
                title='Strict numeric answer', mechanism='Substring parser accepts candidate spam',
                root_cause='Loose parser accepts several candidates', preconditions='A numeric answer parser',
                defense_pattern='Require exactly one numeric answer', evidence_path='SECRET_PATH'), db=path)
            found = self.retrieve(SQLiteKnowledgeSource(path).load())
            self.assertEqual(found[0].invariant_id, 'hub/real-writer#e1')
            self.assertNotIn('SECRET', prompt_context(found)[0])

    def test_actual_sqlite_mirror_is_read_only_and_explicitly_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'invariants.db'
            with closing(sqlite3.connect(path)) as con:
                con.execute('CREATE TABLE environments(env_id TEXT, source TEXT)')
                con.execute('INSERT INTO environments VALUES (?,?)', ('hub/a', 'hub'))
                con.execute('''CREATE TABLE invariants(env_id TEXT, exploit_id TEXT, exploit_class TEXT,
                            title TEXT, mechanism TEXT, preconditions TEXT, defense_pattern TEXT)''')
                con.execute('INSERT INTO invariants VALUES (?,?,?,?,?,?,?)',
                            ('hub/a', 'e1', 'substring-match', 'Substring parser', 'substring parser', 'substring comparison', 'exact answer'))
                con.commit()
            before = path.read_bytes()
            loaded = SQLiteKnowledgeSource(path).load()
            self.assertEqual(self.retrieve(loaded)[0].invariant_id, 'hub/a#e1')
            self.assertTrue(loaded.diagnostics)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(sqlite3.OperationalError): SQLiteKnowledgeSource(Path(tmp) / 'missing.db').load()


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.matches = GraphRetriever(snapshot()).retrieve('substring', '', target_env_id='game/target')
        self.proposal = FixProposal('candidate', ('a',))

    def validate(self, result=None, **kwargs):
        return validate_transfer(self.proposal, self.matches, run_id='run-1', target_env_id='game/target',
                                 replay=lambda candidate, match: result or replay(), **kwargs)

    def test_existing_completion_signature_and_accounting(self):
        client = FakeLLM('{"strategies": ["one candidate"]}')
        wrapped = KnowledgeClient(client, self.matches)
        messages = [{'role': 'user', 'content': 'target'}]
        self.assertEqual(wrapped.complete('system', messages, 2500), client.reply)
        self.assertEqual(wrapped.calls, 1)
        self.assertEqual(messages, [{'role': 'user', 'content': 'target'}])
        self.assertIn('graph neighbour', client.requests[0][0])
        self.assertNotIn('SECRET', client.requests[0][0])

    def test_fixer_validates_applied_ids_and_budget(self):
        client = FakeLLM(json.dumps({'candidate': 'candidate', 'applied_invariant_ids': ['a']}))
        self.assertEqual(propose_fix(client, 'original', 'task', self.matches), self.proposal)
        before = client.calls
        self.assertEqual(propose_fix(client, 'original', 'task', self.matches, max_chars=2), FixProposal('original', ()))
        self.assertEqual(client.calls, before)
        for ids in [['unknown'], ['a', 'a'], []]:
            client.reply = json.dumps({'candidate': 'changed', 'applied_invariant_ids': ids})
            with self.assertRaises(ValueError): propose_fix(client, 'original', '', self.matches)

    def test_orchestrated_transfer_and_empty_store(self):
        client = FakeLLM(json.dumps({'candidate': 'strict', 'applied_invariant_ids': ['a']}))
        result = run_knowledge_transfer(client, snapshot(), original='substring parser', task='one answer',
            target_env_id='game/target', run_id='run-1', replay=lambda *_: replay(), leaderboard_env_ids=frozenset())
        self.assertTrue(result.accepted)
        self.assertEqual(client.calls, 1)
        result = run_knowledge_transfer(client, KnowledgeSnapshot((), ()), original='original', task='',
            target_env_id='game/target', run_id='run-1', replay=lambda *_: self.fail('unexpected replay'),
            leaderboard_env_ids=frozenset())
        self.assertFalse(result.accepted)
        self.assertEqual(client.calls, 1)
        with self.assertRaises(ValueError):
            run_knowledge_transfer(client, snapshot(), original='', task='', target_env_id='game/target',
                run_id='run-1', replay=lambda *_: self.fail('unexpected replay'),
                leaderboard_env_ids=frozenset({'game/target'}))
        self.assertEqual(client.calls, 1)

    def test_malformed_model_output_is_rejected(self):
        for reply in ['not JSON', '[]', '{}', '{"candidate":"x","applied_invariant_ids":null}']:
            with self.assertRaises(ValueError): propose_fix(FakeLLM(reply), 'original', '', self.matches)

    def test_outcomes_and_benign_regression(self):
        for result, expected in [(replay(), 'blocked'), (replay(score_pre_hardened=1), 'not_blocked'),
                                 (replay(score_unhardened=0), 'not_applicable'),
                                 (replay(benign_passed=2), 'not_blocked'),
                                 (replay(score_unhardened=0, score_pre_hardened=1), 'not_blocked')]:
            with self.subTest(expected=expected):
                transfer = self.validate(result)
                self.assertEqual(transfer.applications[0]['outcome'], expected)
                self.assertEqual(transfer.accepted, expected != 'not_blocked')
                self.assertEqual(json.loads(transfer.applications[0]['detail'])['v'], 1)

    def test_reference_and_benign_evidence_required(self):
        for changes in [dict(reference_pre_hardened=0), dict(benign_total=0, benign_passed=0),
                        dict(score_unhardened=float('nan')), dict(benign_passed=4)]:
            with self.assertRaises(ValueError): self.validate(replay(**changes))

    def test_audited_target_rejected_before_replay(self):
        with self.assertRaises(ValueError): self.validate(leaderboard_env_ids=frozenset({'game/target'}))

    def test_forged_source_or_unknown_ids_rejected(self):
        for match in [replace(self.matches[0], env_id='game/target'), replace(self.matches[0], env_id='seed/a')]:
            with self.assertRaises(ValueError):
                validate_transfer(self.proposal, [match], run_id='run-1', target_env_id='game/target', replay=lambda *_: replay())
        self.proposal = FixProposal('candidate', ('unknown',))
        with self.assertRaises(ValueError): self.validate()

    def test_application_identity_is_retry_stable_and_completion_bounded(self):
        first = self.validate(replay(completion='x' * 500))
        self.assertEqual(first, self.validate(replay(completion='x' * 500)))
        self.assertEqual(len(json.loads(first.applications[0]['detail'])['completion']), 200)


if __name__ == '__main__':
    unittest.main()

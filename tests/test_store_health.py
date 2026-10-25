"""Public contract consistency checks, using synthetic rows only."""
from copy import deepcopy

import pytest

from harden.store.health import FIELDS, audit_tables


@pytest.fixture
def tables():
    data = {name: [] for name in FIELDS}
    data['environment'] = [dict(env_id='game/example', source='game', title='Example', status='patched', updated_at=[100])]
    data['exploit'] = [dict(invariant_id='game/example#e1', env_id='game/example', exploit_id='e1',
                           exploit_class='multi-answer', iteration=1, summary='Synthetic example', sample_completion='sample',
                           reward_original=1.0, reward_patched=[0, 0.0], status='patched',
                           evidence_path='results/example.json', confirmed_at=[100])]
    data['invariant'] = [dict(invariant_id='game/example#e1', env_id='game/example', exploit_id='e1',
                             exploit_class='multi-answer', title='One answer per reply', mechanism='Multiple answers accepted',
                             root_cause='Unanchored extraction', preconditions='Multiple candidate outputs',
                             defense_pattern='Require one complete answer', evidence_path='results/example.json', created_at=[101])]
    data['graph_config'] = [dict(id=0, edge_threshold=.45, max_edges_per_node=5)]
    data['rule'] = [dict(rule_id='multi-answer', title='Multi answer', defense_pattern='Require one complete answer', member_count=1, env_count=1)]
    return data


def codes(data):
    return {e['code'] for e in audit_tables(data)['errors']}


def test_valid_contract(tables):
    report = audit_tables(tables)
    assert report['status'] == 'pass' and not report['errors']


@pytest.mark.parametrize('table,field,value,expected', [
    ('environment', 'source', 'unrecognized', 'source'),
    ('environment', 'status', 'unrecognized', 'status'),
    ('invariant', 'exploit_class', 'unrecognized', 'taxonomy'),
    ('invariant', 'env_id', 'missing', 'missing_environment'),
    ('invariant', 'invariant_id', 'wrong', 'composite_id'),
    ('invariant', 'defense_pattern', 'short', 'text'),
    ('invariant', 'title', 'x' * 81, 'title'),
    ('invariant', 'evidence_path', '../outside.json', 'evidence_path'),
    ('invariant', 'evidence_path', '/absolute.json', 'evidence_path'),
    ('invariant', 'created_at', ['bad'], 'field_types'),
    ('exploit', 'iteration', 0, 'iteration'),
    ('exploit', 'reward_original', float('nan'), 'field_types'),
    ('exploit', 'reward_patched', [True, []], 'field_types'),
    ('exploit', 'reward_patched', [1, []], 'patch_status'),
    ('exploit', 'sample_completion', 'x' * 2001, 'sample_length'),
    ('rule', 'member_count', 2, 'rule_counts'),
    ('rule', 'defense_pattern', 'Stale recommendation', 'rule_defense'),
])
def test_rejects_contract_drift(tables, table, field, value, expected):
    tables[table][0][field] = value
    assert expected in codes(tables)


def test_missing_parent_columns_and_duplicates(tables):
    tables['exploit'] = []
    assert 'missing_exploit' in codes(tables)
    tables['invariant'].append(deepcopy(tables['invariant'][0]))
    assert 'duplicate_key' in codes(tables)
    del tables['invariant'][0]['title']
    assert 'columns' in codes(tables)


def test_missing_evidence_and_unpatched_are_warnings(tables, tmp_path):
    tables['exploit'][0].update(status='confirmed', reward_patched=[1, []])
    report = audit_tables(tables, root=tmp_path)
    assert report['status'] == 'pass'
    assert {w['code'] for w in report['warnings']} == {'unpatched_defenses', 'evidence_not_local'}
    evidence = next(w for w in report['warnings'] if w['code'] == 'evidence_not_local')
    assert evidence['distinct_paths'] == evidence['invariants'] == 1


def test_graph_and_transfer_references(tables):
    tables['similarity_edge'] = [dict(edge_id='x|y', a_id='x', b_id='y', score=.3)]
    tables['rule_application'] = [dict(application_key='bad', run_id='run', invariant_id='missing',
                                     target_env_id='missing', outcome='unknown', detail='[]', created_at=[102])]
    assert {'edge_endpoint', 'edge_threshold', 'application_reference', 'application_key', 'outcome', 'application_detail'} <= codes(tables)


def test_edge_limit_is_earlier_neighbor_limit_not_total_degree(tables):
    original = tables['invariant'][0]
    for i in (2, 3):
        tables['invariant'].append(dict(original, invariant_id=f'game/example#e{i}', exploit_id=f'e{i}', created_at=[100+i]))
        tables['exploit'].append(dict(tables['exploit'][0], invariant_id=f'game/example#e{i}', exploit_id=f'e{i}'))
        tables['similarity_edge'].append(dict(edge_id=f'game/example#e1|game/example#e{i}', a_id='game/example#e1', b_id=f'game/example#e{i}', score=.8))
    tables['rule'][0]['member_count'] = 3
    tables['graph_config'][0]['max_edges_per_node'] = 1
    assert 'edge_limit' not in codes(tables)
    tables['similarity_edge'].append(dict(edge_id='game/example#e2|game/example#e3', a_id='game/example#e2', b_id='game/example#e3', score=.8))
    assert 'edge_limit' in codes(tables)

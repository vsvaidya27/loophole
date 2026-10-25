"""Read-only checks of the public store contract; never executes stored evidence.

python -m harden.store.health --snapshot .cache/store-audit/snapshot.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path, PurePosixPath

from .mirror import ENV_STATUSES, EXPLOIT_CLASSES, SOURCES

FIELDS = {
    'environment': 'env_id source title status updated_at',
    'exploit': 'invariant_id env_id exploit_id exploit_class iteration summary sample_completion reward_original reward_patched status evidence_path confirmed_at',
    'invariant': 'invariant_id env_id exploit_id exploit_class title mechanism root_cause preconditions defense_pattern evidence_path created_at',
    'rule_application': 'application_key run_id invariant_id target_env_id outcome detail created_at',
    'similarity_edge': 'edge_id a_id b_id score',
    'rule': 'rule_id title defense_pattern member_count env_count',
    'rule_title': 'rule_id title',
    'graph_config': 'id edge_threshold max_edges_per_node',
}
KEYS = {name: fields.split()[0] for name, fields in FIELDS.items()}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _timestamp(value):
    # SpacetimeDB HTTP encodes Timestamp as a product containing microseconds.
    return isinstance(value, list) and len(value) == 1 and type(value[0]) is int and value[0] >= 0


def _optional_float(value):
    # SATS Option<f32>: [0, payload] = some, [1, []] = none.
    if isinstance(value, list) and len(value) == 2 and type(value[0]) is int:
        if value[0] == 0 and _finite(value[1]):
            return True, value[1]
        if value[0] == 1 and value[1] == []:
            return True, None
    return False, None


def audit_tables(tables: dict, *, root: Path | None = None) -> dict:
    """Check structural consistency, separating it from evidence availability/trust."""
    errors, warnings = [], []

    def issue(code, table, key, detail):
        errors.append({'code': code, 'table': table, 'key': key, 'detail': detail})

    indices = {}
    for name, fields in FIELDS.items():
        indices[name] = {}
        if name not in tables:
            issue('missing_table', name, '', 'Public table was not captured')
        for row in tables.get(name, []):
            key = row.get(KEYS[name])
            if set(row) != set(fields.split()):
                issue('columns', name, key, 'Columns differ from the checked-in public contract')
                continue
            invalid_types = []
            numeric = {'iteration', 'reward_original', 'member_count', 'env_count', 'score', 'id', 'edge_threshold', 'max_edges_per_node'}
            integers = {'iteration', 'member_count', 'env_count', 'id', 'max_edges_per_node'}
            for field, value in row.items():
                valid = (_timestamp(value) if field.endswith('_at') else
                         _optional_float(value)[0] if field == 'reward_patched' else
                         type(value) is int if field in integers else
                         _finite(value) if field in numeric else isinstance(value, str))
                if not valid: invalid_types.append(field)
            if invalid_types:
                issue('field_types', name, key, 'Invalid fields: ' + ', '.join(invalid_types))
                continue
            if key in indices[name]:
                issue('duplicate_key', name, key, 'Duplicate primary key')
            indices[name][key] = row
            for field, value in row.items():
                if field.endswith('_at') and not _timestamp(value):
                    issue('timestamp', name, key, f'{field} is not a SATS timestamp')

    envs, exploits, invariants = (indices[name] for name in ('environment', 'exploit', 'invariant'))
    for key, row in envs.items():
        if not isinstance(key, str) or not key.strip(): issue('env_id', 'environment', key, 'Empty environment ID')
        if row['source'] not in SOURCES: issue('source', 'environment', key, 'Unknown source')
        if row['status'] not in ENV_STATUSES: issue('status', 'environment', key, 'Unknown environment status')
        if not isinstance(row['title'], str) or not row['title'].strip(): issue('title', 'environment', key, 'Empty title')

    missing_evidence, unpatched, signatures = [], [], defaultdict(list)
    for name, rows in (('exploit', exploits), ('invariant', invariants)):
        for key, row in rows.items():
            if row['env_id'] not in envs: issue('missing_environment', name, key, 'Environment does not exist')
            if key != f"{row['env_id']}#{row['exploit_id']}": issue('composite_id', name, key, 'ID does not match environment and exploit')
            if row['exploit_class'] not in EXPLOIT_CLASSES: issue('taxonomy', name, key, 'Unknown exploit class')
            path = row['evidence_path']
            safe = isinstance(path, str) and bool(path.strip()) and not PurePosixPath(path).is_absolute() and '..' not in PurePosixPath(path).parts and '\\' not in path
            if not safe: issue('evidence_path', name, key, 'Expected a nonempty repository-relative evidence path')
            elif root is not None:
                candidate = (root / path).resolve()
                if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
                    missing_evidence.append({'table': name, 'id': key, 'path': path})
            if name == 'exploit':
                if type(row['iteration']) is not int or not 1 <= row['iteration'] <= 5: issue('iteration', name, key, 'Expected iteration 1..5')
                if not _finite(row['reward_original']): issue('reward', name, key, 'Original reward is not finite')
                valid, patched = _optional_float(row['reward_patched'])
                if not valid: issue('reward', name, key, 'Invalid optional patched reward')
                if row['status'] not in ('confirmed', 'patched'): issue('status', name, key, 'Unknown exploit status')
                if (row['status'] == 'patched') != (patched is not None): issue('patch_status', name, key, 'Status and patched reward disagree')
                if len(row['sample_completion']) > 2000: issue('sample_length', name, key, 'Sample exceeds 2000 characters')
                if row['status'] != 'patched': unpatched.append(key)
                continue
            parent = exploits.get(key)
            if parent is None: issue('missing_exploit', name, key, 'Exploit does not exist')
            elif any(row[f] != parent[f] for f in ('env_id', 'exploit_id', 'exploit_class', 'evidence_path')):
                issue('exploit_mismatch', name, key, 'Invariant provenance differs from exploit')
            if not isinstance(row['title'], str) or not 1 <= len(row['title'].strip()) <= 80: issue('title', name, key, 'Title must contain 1..80 characters')
            for field in ('mechanism', 'root_cause', 'preconditions', 'defense_pattern'):
                if not isinstance(row[field], str) or len(row[field].strip()) < 10: issue('text', name, key, f'{field} needs at least 10 characters')
            signatures[tuple(row[f] for f in ('env_id', 'mechanism', 'preconditions', 'defense_pattern'))].append(key)

    config = indices['graph_config'].get(0)
    if config is None or len(indices['graph_config']) != 1:
        issue('graph_config', 'graph_config', 0, 'Expected exactly one config at ID zero')
    elif not _finite(config['edge_threshold']) or not 0 <= config['edge_threshold'] <= 1 or type(config['max_edges_per_node']) is not int or config['max_edges_per_node'] < 0:
        issue('graph_config', 'graph_config', 0, 'Invalid graph limits')
        config = None
    later_counts, incident = Counter(), Counter()
    for key, row in indices['similarity_edge'].items():
        a, b, score = row['a_id'], row['b_id'], row['score']
        if a not in invariants or b not in invariants:
            issue('edge_endpoint', 'similarity_edge', key, 'Missing invariant endpoint')
        else:
            incident.update((a, b))
            later = max((a, b), key=lambda i: (invariants[i]['created_at'], i))
            later_counts[later] += 1
        if a >= b or key != f'{a}|{b}': issue('edge_id', 'similarity_edge', key, 'Expected canonical distinct endpoints')
        if not _finite(score) or not 0 <= score <= 1: issue('edge_score', 'similarity_edge', key, 'Invalid similarity score')
        elif config and score + 1e-6 < config['edge_threshold']: issue('edge_threshold', 'similarity_edge', key, 'Edge is below configured threshold')
    if config:
        for key, count in later_counts.items():
            if count > config['max_edges_per_node']: issue('edge_limit', 'similarity_edge', key, 'Too many earlier neighbors')

    groups = defaultdict(list)
    for row in invariants.values(): groups[row['exploit_class']].append(row)
    for key in set(groups) | set(indices['rule']):
        members, rule = groups.get(key, []), indices['rule'].get(key)
        if not members or rule is None:
            issue('rule_members', 'rule', key, 'Rule family and members disagree')
        else:
            first = min(members, key=lambda row: (row['created_at'], row['invariant_id']))
            if rule['member_count'] != len(members) or rule['env_count'] != len({r['env_id'] for r in members}): issue('rule_counts', 'rule', key, 'Family counts are stale')
            if rule['defense_pattern'] != first['defense_pattern']: issue('rule_defense', 'rule', key, 'Family representative defense is stale')
    for key, row in indices['rule_application'].items():
        if row['invariant_id'] not in invariants or row['target_env_id'] not in envs: issue('application_reference', 'rule_application', key, 'Missing invariant or target')
        if key != f"{row['run_id']}:{row['invariant_id']}->{row['target_env_id']}": issue('application_key', 'rule_application', key, 'Unexpected composite key')
        if row['outcome'] not in ('pre_hardened', 'blocked', 'not_blocked', 'not_applicable'): issue('outcome', 'rule_application', key, 'Unknown transfer outcome')
        try: detail = json.loads(row['detail'])
        except (ValueError, TypeError): detail = None
        if not isinstance(detail, dict) or type(detail.get('v')) is not int or detail['v'] != 1: issue('application_detail', 'rule_application', key, 'Expected version-one JSON object')

    if missing_evidence: warnings.append({'code': 'evidence_not_local', 'records': len(missing_evidence),
                                         'distinct_paths': len({r['path'] for r in missing_evidence}),
                                         'invariants': sum(r['table'] == 'invariant' for r in missing_evidence),
                                         'detail': 'Paths are references, not downloadable evidence; replay cannot be independently verified on this checkout'})
    if unpatched: warnings.append({'code': 'unpatched_defenses', 'records': len(unpatched), 'detail': 'Defense patterns for confirmed, unpatched exploits are recommendations, not validated repairs'})
    duplicates = [ids for ids in signatures.values() if len(ids) > 1]
    if duplicates: warnings.append({'code': 'exact_duplicates', 'groups': duplicates})
    return {'status': 'pass' if not errors else 'fail', 'counts': {name: len(tables.get(name, [])) for name in FIELDS},
            'sources': dict(Counter(r['source'] for r in envs.values())),
            'environment_statuses': dict(Counter(r['status'] for r in envs.values())),
            'exploit_statuses': dict(Counter(r['status'] for r in exploits.values())),
            'classes': {key: len(rows) for key, rows in groups.items()},
            'errors': errors, 'warnings': warnings, 'missing_local_evidence': missing_evidence,
            'unpatched_exploits': unpatched, 'isolated_invariants': sorted(set(invariants) - set(incident)),
            'limitations': ['Private embedding dimensions and cosine values cannot be verified through public tables.',
                            'Structural validity does not establish exploit correctness or defense effectiveness.',
                            'HTTP table reads are sequential; concurrent writers can change the store during capture.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    payload = json.loads(args.snapshot.read_text())
    report = audit_tables(payload['tables'], root=Path(__file__).resolve().parents[2])
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text)
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())

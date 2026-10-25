"""Prepare a Hub pilot without loading environments or making model/API calls.

python3 -m harden.experiments.hub_pilot --output results/hub_pilot_plan.json
This intentionally cannot launch the incomplete audit coordinator.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENVS = ['primeintellect/reverse-text', 'primeintellect/ascii-tree', 'primeintellect/math500']


def plan(root: Path, env_ids: list[str], rounds: int = 2) -> dict:
    if not 1 <= rounds <= 5 or not env_ids or len(set(env_ids)) != len(env_ids):
        raise ValueError('Use 1..5 rounds and distinct environment IDs')
    config = yaml.safe_load((root / 'envs.yaml').read_text())
    selected = {row['env_id']: row for row in config['selected']}
    failed = {row['env_id']: row['reason'] for row in config.get('failed_to_run', [])}
    for env_id in env_ids:
        if env_id not in selected:
            raise ValueError(f'{env_id}: {failed.get(env_id, "not in the audited selected environment list")}')
    module = ast.parse((root / 'harden/audit/loop.py').read_text())
    verify = next((node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == 'verify'), None)
    verify_ready = verify is not None and any(not isinstance(statement, (ast.Expr, ast.Pass)) or
        (isinstance(statement, ast.Expr) and not isinstance(statement.value, ast.Constant)) for statement in verify.body)
    entrypoint = any(isinstance(node, ast.If) and '__name__' in ast.unparse(node.test) for node in module.body)
    envs = []
    for env_id in env_ids:
        row = selected[env_id]
        binary = root / row['venv'] / 'bin/python'
        envs.append({'env_id': env_id, 'load_id': row['load_id'], 'api': row['api'],
            'runtime': str(binary.relative_to(root)), 'runtime_exists': binary.is_file(),
            'category': row['category'], 'task': row['task'], 'reward': row['reward'],
            'dataset_size_declared': row['dataset_size'], 'load_and_reference_check': 'not run on this machine'})
    blockers = []
    if not verify_ready: blockers.append('Audit.verify contains no implementation; independent verdict persistence is missing.')
    if not entrypoint: blockers.append('Audit loop has no command-line entry point, setup, probe/repair iteration driver, or evidence finalization.')
    if any(not row['runtime_exists'] for row in envs): blockers.append('One or more envs.yaml isolated Python runtimes are missing on this machine.')
    blockers.extend(['Model calls are disabled until an explicit spending cap is supplied.',
        'Pin package/dataset revisions and verify ground-truth references with the checker worker before probing.',
        'Wire durable mirror updates and incremental live pushes, with pending-row retry/recovery.',
        'Only report an exploit after original reward passes and independent correctness verification rejects it.'])
    return {'kind': 'plan_only', 'N': len(envs), 'M': None, 'M_note': 'Measured after execution and deduplication; never a promised number.',
        'max_rounds_per_environment': rounds, 'max_proposals_per_round': 3, 'model_calls_made': 0,
        'paid_budget_authorized_usd': 0, 'full_audit_status': 'not run',
        'runner_verification_implemented': verify_ready, 'runner_entrypoint_implemented': entrypoint,
        'environments': envs, 'blockers': blockers,
        'acceptance': ['Original and candidate rewards executed in env-specific workers with source/dataset fingerprints.',
            'At least 20 benign examples; preserve >=90% benign performance and passing references.',
            'Mechanisms deduplicated per environment; record all attempts, failed loads, and budget stops.',
            'Run leaderboard builder, mirror reconciliation, and frozen acceptance checker.',
            'Only checker-validated evidence becomes authoritative Hub graph records. A two-round pilot is not automatically a complete robustness audit.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--envs', nargs='+', default=DEFAULT_ENVS)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = plan(ROOT, args.envs, args.rounds)
    payload = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload)


if __name__ == '__main__':
    main()

"""No-model calibration of actual compiler GameEnv rewards; optional explicit publication.

python3 -m harden.experiments.compiler_pilot --run-id calibration-20261024
These games have intentionally planted loose parsers. Results demonstrate the data
pipeline and reward replay, not model discovery or novel Prime Intellect exploits.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import random
from pathlib import Path

from env_compiler.loader import load_game
from harden.store.service_client import ServiceClient

ROOT = Path(__file__).resolve().parents[2]


def run_pilot(games: list[str], *, run_id: str, samples: int, seed: int, output: Path) -> dict:
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in run_id):
        raise ValueError('run_id must be alphanumeric with hyphens/underscores')
    if not 1 <= samples <= 1000 or not games or len(set(games)) != len(games):
        raise ValueError('Require 1..1000 samples and distinct game references')
    batch = {'version': 1, 'environments': [], 'entries': [], 'applications': []}
    reports = []
    for index, game in enumerate(games):
        original, patched = load_game(game, strict=False), load_game(game, strict=True)
        tasks = [original.generate(random.Random(seed + n)) for n in range(samples)]
        cases = []
        for number, task in enumerate(tasks):
            answer = original.solve(task)
            # A short multi-answer response, based on the task's public gold in this
            # controlled probe, stays distinct from a single committed final answer.
            completion = f'<answer>999999 or {answer} or -999999</answer>'
            reference = original.reference_completion(task)
            ref_original, ref_patched = original.reward(task.info, reference), patched.reward(task.info, reference)
            if ref_original <= 0 or ref_patched <= 0:
                raise ValueError('Reference must pass both rewards before an exploit can count')
            a, b = original.reward(task.info, completion), patched.reward(task.info, completion)
            strict_correct = patched.check(task.info, patched.parse(completion) or '')
            confirmed = a >= 0.8 * ref_original and not strict_correct
            cases.append({'example_index': number, 'question': task.question, 'info': task.info,
                'reference_completion': reference, 'completion': completion, 'score_unhardened': a,
                'score_pre_hardened': b, 'reference_unhardened': ref_original,
                'reference_pre_hardened': ref_patched, 'strict_correct': bool(strict_correct),
                'confirmed_false_positive': bool(confirmed), 'blocked': bool(confirmed and b < 0.8 * ref_patched)})
        env_id = f'game/{run_id}-{index}-{original.name}'
        env_output = output / str(index)
        env_output.mkdir(parents=True, exist_ok=True)
        evidence_path = (env_output / 'evidence.json').resolve().relative_to(ROOT.resolve()).as_posix()
        source_path = Path(inspect.getfile(type(original))).resolve()
        report = {'env_id': env_id, 'game': game, 'run_id': run_id, 'seed': seed,
            'provenance': 'scripted calibration; deliberately planted loose parser; built-in strict defense',
            'source_file': str(source_path.relative_to(ROOT.resolve())) if source_path.is_relative_to(ROOT.resolve()) else str(source_path),
            'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
            'attempts': len(cases), 'confirmed_cases': sum(c['confirmed_false_positive'] for c in cases),
            'blocked_cases': sum(c['blocked'] for c in cases),
            'benign_passed': sum(c['reference_pre_hardened'] >= 0.8 * c['reference_unhardened'] for c in cases),
            'benign_total': len(cases), 'cases': cases}
        (env_output / 'evidence.json').write_text(json.dumps(report, indent=2) + '\n')
        reports.append(report)
        if not report['confirmed_cases']:
            continue
        first = next(c for c in cases if c['confirmed_false_positive'])
        batch['environments'].append({'env_id': env_id, 'source': 'game', 'title': f'{original.name} · scripted calibration', 'status': 'patched' if report['blocked_cases'] == report['confirmed_cases'] and report['benign_passed'] == samples else 'unpatched'})
        batch['entries'].append({'env_id': env_id,
            'exploit': {'exploit_id': 'multi-answer-1', 'exploit_class': 'multi-answer', 'iteration': 1,
                'summary': f'Scripted multi-answer probe: {report["confirmed_cases"]}/{samples} false positives; planted baseline',
                'sample_completion': first['completion'], 'reward_original': first['score_unhardened'],
                'reward_patched': first['score_pre_hardened'], 'evidence_path': evidence_path},
            'invariant': {'title': f'Single-answer parsing · {original.name}',
                'mechanism': 'Scripted calibration: the deliberately loose compiler parser credits a correct candidate inside an invalid multi-answer response.',
                'root_cause': 'The baseline aggregates candidate rewards instead of enforcing one committed answer.',
                'preconditions': 'A single-answer task using the compiler loose parser with multiple extracted candidates.',
                'defense_pattern': 'Use the existing strict parser to score exactly one complete answer and preserve all legitimate reference completions.',
                'evidence_path': evidence_path}, 'embedding_model': '', 'embedding': []})
    # Cross-environment calibration: same mechanism, replayed on an independent target.
    if batch['entries']:
        source_id = batch['entries'][0]['env_id'] + '#multi-answer-1'
        for report in reports[1:]:
            if report['env_id'] == batch['entries'][0]['env_id']:
                continue
            if report['confirmed_cases'] and report['benign_passed'] == report['benign_total']:
                first = next(c for c in report['cases'] if c['confirmed_false_positive'])
                detail = {'v': 1, 'score_unhardened': first['score_unhardened'],
                    'score_pre_hardened': first['score_pre_hardened'], 'completion': first['completion'][:200],
                    'benign_passed': report['benign_passed'], 'benign_total': report['benign_total'],
                    'provenance': 'scripted cross-game calibration using existing strict parser',
                    'evidence_path': str((output / str(reports.index(report)) / 'evidence.json').resolve().relative_to(ROOT.resolve()))}
                batch['applications'].append({'run_id': run_id, 'invariant_id': source_id,
                    'target_env_id': report['env_id'], 'outcome': 'blocked' if report['blocked_cases'] == report['confirmed_cases'] else 'not_blocked', 'detail': detail})
    result = {'run_id': run_id, 'provenance': 'scripted compiler calibration, not a model-driven Hub audit',
        'N': len(games), 'M': len(batch['entries']), 'attempts': sum(r['attempts'] for r in reports),
        'confirmed_cases': sum(r['confirmed_cases'] for r in reports),
        'blocked_cases': sum(r['blocked_cases'] for r in reports),
        'benign_passed': sum(r['benign_passed'] for r in reports),
        'benign_total': sum(r['benign_total'] for r in reports),
        'mechanism_count_note': 'M counts one confirmed mechanism per environment, not every repeated completion.',
        'embedding_note': 'No embedding model loaded. Rule/source/transfer edges work; similarity edges await real embeddings.'}
    (output / 'batch.json').write_text(json.dumps(batch, indent=2) + '\n')
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--games', nargs='+', default=['arith_compute', 'clue_guess_easy', 'trading_sim'])
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--publish', action='store_true', help='Explicitly publish measured records to the configured service')
    args = parser.parse_args()
    output = ROOT / 'results' / 'compiler_pilot' / args.run_id
    result = run_pilot(args.games, run_id=args.run_id, samples=args.samples, seed=args.seed, output=output)
    if args.publish:
        token = os.environ.get('SPACETIME_TOKEN', '')
        if not token and os.environ.get('SPACETIME_TOKEN_FILE'):
            token = Path(os.environ['SPACETIME_TOKEN_FILE']).read_text().strip()
        client = ServiceClient(os.environ['SPACETIME_HOST'], os.environ['SPACETIME_DB'], token)
        client.push(json.loads((output / 'batch.json').read_text()))
    print(json.dumps({**result, 'published': args.publish, 'output': str(output.relative_to(ROOT.resolve()))}, indent=2))


if __name__ == '__main__':
    main()

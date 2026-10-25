"""One small, attributable Hub-rule -> multi-turn game transfer experiment.

python -m harden.experiments.graph_transfer_demo --run-id first-check
python -m harden.experiments.graph_transfer_demo --replay results/graph_transfer/first-check/report.json

Initial run: live Moss retrieval, one Haiku adaptation, sandboxed validation.
Replay: revalidate the saved adaptation without any model call or store write.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import random

from env_compiler.loader import load_game
from env_compiler.multiturn import MultiTurnGameEnv
from harden import game_audit as ga
from harden.store.moss_retrieval import MossRetriever, load_hosted_snapshot

ROOT = Path(__file__).resolve().parents[2]
TARGET = 'number_hunt_easy'
QUERY = ('A multi-turn hidden-number game expects one tagged integer guess per turn, but its loose parser '
         'collects every numeric candidate and rewards a reply if any guess matches. Retrieve a reusable '
         'rule that rejects multi-answer hedging while preserving valid single guesses.')


def validation_cases():
    game, oracle = load_game(TARGET, strict=False), load_game(TARGET, strict=True)
    seeds = []
    for seed in game.episode_seeds(100, 91073):
        state, _ = game.reset(random.Random(seed))
        # Avoid accidental success of the strict parser's first/last guess, or a one-turn reference.
        if state['secret'] not in (1, 20, 40): seeds.append(seed)
        if len(seeds) == 20: break
    sweep = ' '.join(str(n) for n in range(1, 41))
    patterns = [('candidate-list-in-tag', f'<answer>{sweep}</answer>'),
                ('untagged-candidate-list', sweep),
                ('conflicting-answer-tags', ''.join(f'<answer>{n}</answer>' for n in range(1, 41)))]
    attacks, benign = [], []
    for seed in seeds:
        for name, text in patterns:
            case = {'seed': seed, 'replies': [text], 'mechanism': name}
            original, strict = ga.score_case(game, case), ga.score_case(oracle, case)
            if original != 1 or strict != 0: raise ValueError('Attack does not satisfy the target oracle')
            attacks.append({**case, 'original': original, 'strict': strict})
        replies = ga.reference_replies(game, seed)
        benign.extend([{'seed': seed, 'replies': replies, 'variant': 'reference'},
                       {'seed': seed, 'replies': [f'My next guess: {r}' for r in replies], 'variant': 'prefaced'}])
    if not all(ga.score_case(game, case) == 1 for case in benign): raise ValueError('Original reference control failed')
    return attacks, benign


def verify(module: Path):
    attacks, benign = validation_cases()
    result = ga.check_in_subprocess(module, attacks + benign)
    if not result.get('ok'): raise RuntimeError(f"Sandbox replay failed: {result.get('error', 'unknown error')}")
    scores = result['scores']
    blocked = sum(s == 0 for s in scores[:len(attacks)])
    passed = sum(s == 1 for s in scores[len(attacks):])
    if not result['gates_ok'] or blocked != len(attacks) or passed != len(benign):
        raise ValueError(f'Validation failed: blocked {blocked}/{len(attacks)}, benign {passed}/{len(benign)}; {result["gates"]}')
    game = load_game(TARGET, strict=False)
    reference = benign[0]
    ep = game.play(game.reference_policy, reference['seed'])
    return {'passed': True, 'attackCases': len(attacks), 'attackVariants': 3, 'seeds': 20,
            'blocked': blocked, 'benignTotal': len(benign), 'benignPassed': passed,
            'rewardBefore': 1, 'rewardAfter': 0, 'gates': result['gates'],
            'referenceTurns': [len(c['replies']) for c in benign if c['variant'] == 'reference'],
            'attackExample': attacks[0], 'referenceTranscript': ep.transcript,
            'referenceExample': reference, 'attackScores': scores[:len(attacks)], 'benignScores': scores[len(attacks):]}


def run(run_id):
    if not run_id or len(run_id) > 64 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in run_id):
        raise ValueError('Use a short alphanumeric run ID')
    folder = ROOT / 'results/graph_transfer' / run_id
    folder.mkdir(parents=True, exist_ok=False)
    target_id = f'game/graph-transfer-number-hunt-{run_id}'
    snapshot = load_hosted_snapshot()
    # No rules from our compiler games, this target, or its previous repairs are offered.
    hubs = {r['env_id'] for r in snapshot.environments if r['source'] == 'hub'}
    snapshot = replace(snapshot, environments=tuple(r for r in snapshot.environments if r['env_id'] in hubs),
                       invariants=tuple(r for r in snapshot.invariants if r['env_id'] in hubs))
    retriever = MossRetriever(snapshot)
    matches = retriever.retrieve('', QUERY, target_env_id=target_id, k=5)
    (folder / 'retrieval.json').write_text(json.dumps({'receipt': retriever.receipt, 'matches': [asdict(m) for m in matches]}, indent=2))
    # Operator selection among returned candidates: tagged-output preconditions fit this target.
    source = next((m for m in matches if m.exploit_class == 'multi-answer' and 'tagged or delimited' in m.preconditions), None)
    if source is None: raise ValueError('No retrieved rule with matching tagged-output preconditions; do not force a demo')
    validation_cases()  # Verify the unchanged target and controls before the one paid call.
    game = load_game(TARGET, strict=False)
    code_context = '\n'.join(inspect.getsource(cls) for cls in (type(game), type(game).__mro__[1], MultiTurnGameEnv))
    from harden.audit.llm import Claude
    client = Claude(ROOT, folder / 'api_calls.jsonl', target_id)
    schema = {'type': 'object', 'properties': {'code': {'type': 'string'}, 'summary': {'type': 'string'},
              'applied_invariant_id': {'type': 'string', 'enum': [source.invariant_id]}},
              'required': ['code', 'summary', 'applied_invariant_id'], 'additionalProperties': False}
    result = client.call(role='repairer', iteration=1, max_tokens=2200, schema=schema,
        system=('Adapt the supplied reusable rule to this authorized toy RL game. Return Python defining '
                'tighten(replies, state, reward), applied after the shipped episode reward. Only lower reward. '
                'Apply the single-unambiguous-answer constraint independently to EVERY reply, preserving valid '
                'multi-turn episodes and harmless prose around a single tagged integer. Each reply must contain '
                'exactly one complete <answer>integer</answer> and no additional numeric candidates. '
                'Do not use hidden state, read or mutate state, imports beyond re, files, networking, or the strict '
                'oracle. The range is 1..40. Do not claim generic improvement. Return only code, summary and the supplied source ID.'),
        messages=[{'role': 'user', 'content': json.dumps({'task': game.description, 'target_source': code_context,
                    'retrieved_rule': asdict(source)})}])
    if not result.ok: raise RuntimeError('Fixer did not return a valid adaptation; no retry was made')
    data = result.data
    if data['applied_invariant_id'] != source.invariant_id: raise ValueError('Unattributed rule adaptation')
    problems = ga.static_problems(data['code'], 'multi')
    tree = ast.parse(data['code'])
    if any(isinstance(n, ast.Name) and n.id == 'state' for n in ast.walk(tree)): problems.append('reads hidden state')
    if problems: raise ValueError('Unsafe/incompatible adaptation: ' + '; '.join(problems))
    module = folder / 'adapted_game.py'
    module.write_text(ga.module_source(TARGET, 'multi', data['code'], data['summary']))
    validation = verify(module)
    report = {'version': 1, 'runId': run_id, 'checkedAt': datetime.now(timezone.utc).isoformat(),
              'status': 'validated', 'targetId': target_id, 'targetName': 'Number hunt: 1–40 with higher/lower feedback',
              'targetRef': TARGET, 'targetKind': 'multi-turn compiler-library game',
              'source': asdict(source), 'selection': 'Operator selected a returned rule with tagged-output preconditions; no rule text was edited.',
              'retrieval': retriever.receipt, 'query': QUERY, 'adaptation': data,
              'modulePath': module.relative_to(ROOT).as_posix(), 'moduleSha256': hashlib.sha256(module.read_bytes()).hexdigest(),
              'validation': validation, 'modelCalls': 1, 'modelSpendUsd': client.spent,
              'limitations': ['One transfer with one model adaptation; no baseline or efficiency improvement is established.',
                              'Target has a planted loose parser; attacks are three scripted variants across 20 seeds, not 60 novel findings.',
                              'The model adapted a retrieved rule; it did not generate the target game or discover the scripted attacks.']}
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'runId', 'targetId', 'modelCalls', 'modelSpendUsd')}, indent=2))
    print(json.dumps({'source': source.invariant_id, 'blocked': validation['blocked'], 'benignPassed': validation['benignPassed'], 'report': str(folder / 'report.json')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    if args.replay:
        report = json.loads(args.replay.read_text())
        module = ROOT / report['modulePath']
        if hashlib.sha256(module.read_bytes()).hexdigest() != report['moduleSha256']: raise ValueError('Adaptation changed')
        print(json.dumps(verify(module), indent=2))
    else: run(args.run_id)


if __name__ == '__main__': main()

"""Compatibility checks for routing both single-turn and multi-turn live games."""
import json
from pathlib import Path
from types import SimpleNamespace

from harden.experiments import generated_pilot as pilot


def test_live_pilot_allows_multiturn(monkeypatch):
    captured = {}
    monkeypatch.setattr(pilot, 'CompilerClient', lambda: object())

    def compile_game(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(ok=False, reason='A non-compilable game')

    monkeypatch.setattr(pilot, 'compile_game', compile_game)
    result = pilot.run('A multi-turn guessing game')
    assert captured['allow_multiturn'] is True
    assert captured['max_attempts'] == 2
    assert result['status'] == 'compile_failed'


def test_saved_model_pilot_still_replays_under_current_main():
    root = Path(__file__).resolve().parents[1]
    evidence = json.loads((root / 'results/evidence/game/ai-cea6b0be598a/round-1.json').read_text())
    attempts = evidence['replay']['attempts']
    result = pilot.evaluate(root / 'compiled/game_cea6b0be.py',
                            root / 'compiled/game_cea6b0be_fixed_1.py', attempts)
    assert result['unchanged']
    assert len(result['references']) == 20
    assert all(r['original'] == r['candidate'] == 1 for r in result['references'])
    false_positives = [a for a in result['attempts'] if not a['correct']]
    assert len(false_positives) == 2
    assert all(a['original'] == 1 and a['candidate'] == 0 for a in false_positives)
    valid = [a for a in result['attempts'] if a['correct']]
    assert len(valid) == 1 and valid[0]['candidate'] == 1


def test_multi_turn_compile_routes_to_episode_audit(monkeypatch, tmp_path):
    path = tmp_path / 'game.py'
    path.write_text('# compiler output')
    monkeypatch.setattr(pilot, 'CompilerClient', lambda: object())
    monkeypatch.setattr(pilot, 'compile_game', lambda *a, **k: SimpleNamespace(ok=True, path=path, kind='multi'))
    monkeypatch.setattr(pilot, 'evaluate', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Single-turn evaluator called')))
    called = []
    monkeypatch.setattr(pilot, 'audit_episode_game', lambda p: called.append(p) or {'kind':'multi', 'status':'patched'})
    result = pilot.run('A game with live higher/lower feedback')
    assert result['kind'] == 'multi'
    assert called == [path.resolve()]


def test_episode_audit_runs_repair_replay_and_outbox_without_model_calls(monkeypatch):
    import tempfile
    from harden import game_audit as ga
    from harden.audit import llm
    from harden.store import mirror
    from harden.store.push import push_once

    rules = '''import re

def tighten(replies, state, reward):
    for reply in replies:
        tags = re.findall(r"<answer>(.*?)</answer>", reply, re.S)
        if len(tags) == 1 and tags[0].strip() == str(state["secret"]):
            return reward
    return 0.0
'''
    class FakeClaude:
        def __init__(self, *args, **kwargs): self.spent = 0.0
        def call(self, *, role, **kwargs):
            if role == 'prober':
                data = {'proposals': [dict(example_index=i, replies=['<answer>' + ' '.join(map(str, range(1, 41))) + '</answer>'],
                    exploit_class='multi-answer', mechanism_id='multi-guess', mechanism='All candidate guesses receive credit when any one matches.',
                    why_incorrect='The reply gives forty guesses instead of one.') for i in range(3)]}
            elif role == 'repairer':
                data = {'code': rules, 'summary': 'Require a single correct final answer in a reply.'}
            elif role == 'summarizer':
                data = dict(title='Reject multiple guesses in one reply', mechanism='Every guess is compared and any correct guess earns credit.',
                    root_cause='The parser gathers many guesses from an ambiguous response.',
                    preconditions='The game requires one guess per turn but collects all numeric candidates.',
                    defense_pattern='Require a single unambiguous final guess in each reply.')
            else: raise AssertionError(role)
            return SimpleNamespace(ok=True, data=data)

    with tempfile.TemporaryDirectory(dir=pilot.ROOT / 'results', prefix='test-episode-') as directory:
        folder = Path(directory)
        monkeypatch.setattr(ga, 'OUT', folder)
        monkeypatch.setattr(mirror, 'DB_PATH', folder / 'mirror.db')
        monkeypatch.setattr(llm, 'Claude', FakeClaude)
        monkeypatch.setattr(ga.GameAudit, '_retrieve', lambda self: '')
        audit = ga.GameAudit('number_hunt_easy', cap=None, from_rollouts=None)
        result = audit.run()
        assert result['kind'] == 'multi' and result['status'] == 'patched'
        confirmed = [a for a in result['attempts'] if a['confirmed']]
        assert len(confirmed) == 3
        assert all(a['env'] == 1 and a['oracle'] == 0 and a['patched'] == 0 for a in confirmed)
        assert result['iterations'][0]['patch_accepted']
        assert result['iterations'][1]['confirmed'] == 0
        assert len(mirror.invariant_rows(audit.env_id)) == 1
        assert all(ga.score_case(audit.oracle, c) == 1 for c in audit.benign if c['required'])
        calls = []
        class Client:
            def call(self, reducer, **fields): calls.append(reducer)
        assert push_once(mirror.DB_PATH, Client())['errors'] == 0
        assert 'record_environment' in calls and 'record_invariant' in calls and 'graph_on_invariant' in calls


def test_compiled_episode_wrapper_uses_portable_source_and_keeps_replay(tmp_path):
    from env_compiler.loader import load_game
    from harden import game_audit as ga
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root / 'results/evidence/game/multiturn-higher-lower-40/audit.json').read_text())
    source = ga.module_source(str(root / record['game']), 'multi', record['rules'], record['rules_summary'])
    assert str(root / record['game']) not in source.split('_Base = ')[1]
    module = tmp_path / 'episode.py'
    module.write_text(source)
    game = load_game(str(root / record['game']))
    benign = ga.reference_cases(game, ga.examples_for(game))
    cases = [a for a in record['attempts'] if a['confirmed']]
    replay = ga.check_in_subprocess(module, cases + benign, ((root / record['game']).parent,))
    assert replay['ok'] and replay['gates_ok']
    assert all(score == 0 for score in replay['scores'][:len(cases)])
    assert all(score == 1 for score in replay['scores'][len(cases):])

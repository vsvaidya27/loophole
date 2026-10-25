import re
import asyncio
import random

import pytest

from env_compiler import GAMES, MULTI_GAMES, validate
from env_compiler import compile as comp
from env_compiler.loader import load_game
from tests.test_compile import FakeClient


@pytest.mark.parametrize("name", MULTI_GAMES)
@pytest.mark.parametrize("strict", [True, False])
def test_episode_gates(name, strict):
    report = validate(MULTI_GAMES[name](strict=strict))
    assert report.ok, str(report)


def test_multi_games_are_kept_apart_from_single_turn():
    assert not set(GAMES) & set(MULTI_GAMES)
    assert all(g.kind == "single" for g in GAMES.values())
    assert all(g.kind == "multi" for g in MULTI_GAMES.values())
    assert load_game("number_hunt").kind == "multi" and load_game("arith_compute").kind == "single"


@pytest.mark.parametrize("name", MULTI_GAMES)
def test_reference_policy_wins_within_budget_on_many_seeds(name):
    game = MULTI_GAMES[name]()
    for seed in game.episode_seeds(300, 7):
        ep = game.play(game.reference_policy, seed)
        assert ep.reward == 1.0 and ep.turns <= game.max_turns


def test_episodes_are_deterministic_given_a_seed():
    game = MULTI_GAMES["number_hunt"]()
    a, b = game.play(game.reference_policy, 5), game.play(game.reference_policy, 5)
    assert a.transcript == b.transcript


def test_number_hunt_feedback_and_loose_exploit():
    strict, loose = MULTI_GAMES["number_hunt"](strict=True), MULTI_GAMES["number_hunt"](strict=False)
    state, _ = strict.reset(random.Random(3))
    secret = state["secret"]
    message, done = strict.step(state, f"<answer>{secret + 1}</answer>")
    assert message == "Lower." and not done
    message, done = strict.step(state, f"<answer>{secret}</answer>")
    assert done and strict.reward(state) == 1.0
    spam = " ".join(str(i) for i in range(1, 201))
    s2, _ = strict.reset(random.Random(4))
    assert strict.step(s2, spam)[1] is False and strict.reward(s2) == 0.0  # untagged reply: no guess
    l2, _ = loose.reset(random.Random(4))
    assert loose.step(l2, spam)[1] is True and loose.reward(l2) == 1.0  # listing every number wins


def test_invalid_replies_cost_a_turn_but_never_crash():
    game = MULTI_GAMES["live_mastermind"]()
    state, _ = game.reset(random.Random(1))
    for reply in ["", "<answer></answer>", "<answer>111</answer>", "<answer>12</answer>", "x" * 5000]:
        message, _ = game.step(state, reply)
        assert message.startswith("Invalid guess")
    assert state["turns"] == 5 and state["history"] == []


def test_single_turn_trainer_rejects_multi_turn_games():
    from trainer.common import require_single_turn

    with pytest.raises(SystemExit):
        require_single_turn(MULTI_GAMES["number_hunt"]())
    require_single_turn(GAMES["arith_compute"]())  # no error


def test_verifiers_multiturn_adapter_runs_an_episode():
    import verifiers as vf

    from env_compiler.verifiers_env import load_environment

    env = load_environment("number_hunt", num_train=4, num_eval=2)
    row = dict(env.get_dataset()[0])
    state = vf.State(input={"prompt": row["prompt"], "answer": "", "info": row["info"]})
    asyncio.run(env.setup_state(state))
    secret = state["game_state"]["secret"]
    reply = asyncio.run(env.env_response([{"role": "assistant", "content": f"<answer>{secret}</answer>"}], state))
    assert reply[0]["content"] == "Correct!" and state["final_env_response"]
    assert env.game.reward(state["game_state"]) == 1.0


def _fit(kind):
    return '{"kind": "%s", "reason": "r"}' % kind


def test_compiler_compiles_multiturn_by_default_and_refuses_it_when_single_only(monkeypatch, tmp_path):
    monkeypatch.setattr(comp, "CACHE", tmp_path / "cache")
    client = FakeClient([_fit("multi")])
    result = comp.compile_game("guess my number with hints", tmp_path, client=client, allow_multiturn=False)
    assert not result.ok and "multi-turn" in result.reason

    good = (comp.PKG / "games" / "multiturn_games.py").read_text().split("class NumberHuntEasy")[0]
    good = good.replace("from ..", "from env_compiler.").replace("from .clue_guess import", "from env_compiler.games.clue_guess import")
    good = good.replace("class NumberHunt(", "class Game(")
    client = FakeClient([_fit("multi"), f"```python\n{good}\n```"])
    result = comp.compile_game("guess my number with hints", tmp_path / "out", client=client)
    assert result.ok, result.reason
    assert result.kind == "multi"


def test_compiler_still_treats_old_fits_replies_as_single_turn(monkeypatch, tmp_path):
    monkeypatch.setattr(comp, "CACHE", tmp_path / "cache")
    assert comp.check_fit(FakeClient(['{"fits": true, "reason": "ok"}']), "x")[0] == "single"
    assert comp.check_fit(FakeClient(['{"fits": false, "reason": "no"}']), "y")[0] == "reject"


def test_loophole_gate_passes_the_builtin_games_and_catches_a_dead_loose_parser():
    from env_compiler.gates import loophole_report

    for name in MULTI_GAMES:
        report = loophole_report(MULTI_GAMES[name])
        assert report["ok"], report["text"]

    class FirstGuessOnly(MULTI_GAMES["number_hunt_easy"]):
        """Loose mode collects every number but only ever checks the first: no working loophole."""

        def answers(self, reply):
            return super().answers(reply)[:1]

    report = loophole_report(FirstGuessOnly)
    assert not report["ok"] and "ANY listed guess" in report["text"]


def test_snake_live_one_move_per_turn_and_the_loose_move_dump():
    strict, loose = MULTI_GAMES["snake_live"](strict=True), MULTI_GAMES["snake_live"](strict=False)
    seed = strict.episode_seeds(1, 11)[0]
    plan = [t for who, t in strict.play(strict.reference_policy, seed).transcript if who == "agent"]
    assert strict.play(strict.reference_policy, seed).reward == 1.0
    dump = "".join(re.sub(r"</?answer>", "", m) for m in plan)  # the whole path in one reply
    for game, expected in ((loose, 1.0), (strict, 0.0)):
        state, _ = game.reset(random.Random(seed))
        game.step(state, f"<answer>{dump}</answer>")
        assert game.reward(state) == expected  # loose runs every move; strict reads "RDDL..." as no move
    state, _ = strict.reset(random.Random(seed))
    message, done = strict.step(state, "<answer>up</answer>")
    assert state["moves"] == "U" and not done and "Next move?" in message

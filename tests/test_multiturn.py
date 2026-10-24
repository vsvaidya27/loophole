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


def test_compiler_refuses_multiturn_by_default_and_allows_it_with_the_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(comp, "CACHE", tmp_path / "cache")
    result = comp.compile_game("guess my number with hints", tmp_path, client=FakeClient([_fit("multi")]))
    assert not result.ok and "multi-turn" in result.reason

    good = (comp.PKG / "games" / "multiturn_games.py").read_text()
    good = good.replace("from ..", "from env_compiler.").replace("from .clue_guess import", "from env_compiler.games.clue_guess import")
    good = good.replace("class NumberHunt(", "class Game(")
    client = FakeClient([_fit("multi"), f"```python\n{good}\n```"])
    result = comp.compile_game("guess my number with hints", tmp_path / "out", client=client, allow_multiturn=True)
    assert result.ok, result.reason


def test_compiler_still_treats_old_fits_replies_as_single_turn(monkeypatch, tmp_path):
    monkeypatch.setattr(comp, "CACHE", tmp_path / "cache")
    assert comp.check_fit(FakeClient(['{"fits": true, "reason": "ok"}']), "x")[0] == "single"
    assert comp.check_fit(FakeClient(['{"fits": false, "reason": "no"}']), "y")[0] == "reject"

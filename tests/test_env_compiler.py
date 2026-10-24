import asyncio

import pytest

from env_compiler import GAMES, validate
from env_compiler.games.clue_guess import consistent


@pytest.mark.parametrize("name", GAMES)
@pytest.mark.parametrize("strict", [True, False])
def test_validation_gates(name, strict):
    report = validate(GAMES[name](strict=strict))
    assert report.ok, str(report)


@pytest.mark.parametrize("name", GAMES)
def test_strict_parser_rejects_untagged_and_spam(name):
    env = GAMES[name](strict=True)
    task = env.tasks(1, 7)[0]
    answer = env.solve(task)
    assert env.reward(task.info, answer) == 0.0  # no tags
    assert env.reward(task.info, f"<answer>{answer}</answer>") == 1.0
    assert env.reward(task.info, f"<answer>{answer} 000</answer>") == 0.0


def test_loose_parser_is_hackable_by_spamming_candidates():
    env = GAMES["clue_guess"](strict=False)
    strict = GAMES["clue_guess"](strict=True)
    task = env.tasks(1, 3)[0]
    spam = " ".join(f"{i:03d}" for i in range(1000))
    assert env.reward(task.info, spam) == 1.0
    assert strict.reward(task.info, f"<answer>{spam}</answer>") == 0.0


def test_clues_identify_unique_secret():
    env = GAMES["clue_guess"]()
    for t in env.tasks(30, 5):
        assert consistent(t.info["secret"], t.info["clues"])


@pytest.mark.parametrize("name", GAMES)
def test_verifiers_environment_scores_reference(name):
    from env_compiler.verifiers_env import load_environment

    env = load_environment(name, num_train=8, num_eval=4)
    game = GAMES[name]()
    row = dict(env.get_dataset()[0])
    task = game.tasks(8, 1000)[0]
    assert row["prompt"][0]["content"] == task.question
    assert game.reward(row["info"], game.reference_completion(task)) == 1.0
    assert len(env.get_eval_dataset()) == 4

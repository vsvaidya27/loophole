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
def test_strict_parser_needs_answer_tags(name):
    env = GAMES[name](strict=True)
    task = env.tasks(1, 7)[0]
    answer = env.solve(task)
    assert env.reward(task.info, answer) == 0.0  # no tags
    assert env.reward(task.info, f"<answer>{answer}</answer>") == 1.0


@pytest.mark.parametrize("name", ["arith_target", "clue_guess", "arith_compute", "clue_guess_easy"])
def test_exact_match_games_reject_trailing_junk(name):
    env = GAMES[name](strict=True)
    task = env.tasks(1, 7)[0]
    assert env.reward(task.info, f"<answer>{env.solve(task)} 000</answer>") == 0.0


def test_word_list_games_cap_and_loose_exploit():
    strict, loose = GAMES["anagrams"](strict=True), GAMES["anagrams"](strict=False)
    task = strict.tasks(1, 11)[0]
    best = task.info["best"]
    from env_compiler.games.wordgames import spellable
    from env_compiler.words import TOP_K

    others = [w for w in spellable(task.info["letters"]) if w not in best]
    padded = " ".join(others[:TOP_K] + best)  # good words after the cap
    assert strict.reward(task.info, f"<answer>{padded}</answer>") < 1.0
    assert loose.reward(task.info, padded) == 1.0
    assert strict.reward(task.info, f"<answer>{' '.join(best + best)}</answer>") == 1.0  # repeats add nothing
    assert strict.reward(task.info, "<answer>zzz qqq xxx</answer>") == 0.0


def test_word_hunt_requires_adjacent_path():
    from env_compiler.games.wordgames import _grid_words
    from env_compiler.words import words

    env = GAMES["word_hunt"](strict=True)
    task = env.tasks(1, 4)[0]
    traceable = _grid_words(task.info["grid"])
    assert all(env.is_valid(task.info, w) for w in task.info["best"])
    # A dictionary word spelled from grid letters but not traceable must be rejected.
    untraceable = [w for w in words() if set(w) <= set(task.info["grid"]) and w not in traceable]
    assert untraceable and not env.is_valid(task.info, untraceable[0])


def test_snake_simulator():
    env = GAMES["snake"](strict=True)
    task = env.tasks(1, 2)[0]
    assert env.reward(task.info, f"<answer>{task.info['plan']}</answer>") == 1.0
    assert env.reward(task.info, "<answer>UUUUUUUUUUUU</answer>") < 1.0  # walks into the wall
    assert len(env.frames(task.info, task.info["plan"])) == len(task.info["plan"]) + 1


def test_lights_out_solution_and_partial_credit():
    env = GAMES["lights_out"](strict=True)
    task = env.tasks(1, 2)[0]
    assert env.reward(task.info, f"<answer>{task.info['plan']}</answer>") == 1.0
    assert env.reward(task.info, "<answer>abc</answer>") == 0.0


def test_trading_hedge_and_oversize_exploits():
    strict, loose = GAMES["trading_sim"](strict=True), GAMES["trading_sim"](strict=False)
    task = strict.tasks(1, 9)[0]
    right = "BUY" if task.info["future"] > task.info["prices"][-1] else "SELL"
    wrong = "SELL" if right == "BUY" else "BUY"
    assert strict.reward(task.info, f"<answer>{right} 5</answer>") == 1.0
    assert strict.reward(task.info, f"<answer>{wrong} 5</answer>") == 0.0
    assert strict.reward(task.info, f"<answer>{right} 500</answer>") == 0.0  # over the size limit
    assert loose.reward(task.info, f"BUY 5 or SELL 5") == 1.0  # hedging
    assert loose.reward(task.info, f"{right} 500") == 1.0


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

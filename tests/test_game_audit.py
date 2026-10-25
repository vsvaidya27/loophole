"""Offline checks for the game hardening loop (no API calls)."""

import random

from env_compiler.loader import load_game
from harden import game_audit as ga

ONE_GUESS_RULE = '''
import re

_TAG = re.compile(r"<answer>(.*?)</answer>", re.S)


def tighten(replies, state, reward):
    for reply in replies:
        tags = _TAG.findall(reply)
        if tags and tags[-1].strip() == str(state["secret"]):
            return reward
    return 0.0
'''

LAST_TAG_RULE = '''
import re


def tighten(text, info, reward):
    tags = re.findall(r"<answer>(.*?)</answer>", text)
    return reward if tags and tags[-1].strip() == str(info["answer"]) else 0.0
'''


def test_replay_scores_reply_sequences_on_a_fresh_episode():
    loose, strict = load_game("number_hunt_easy", strict=False), load_game("number_hunt_easy", strict=True)
    seed = loose.episode_seeds(1, 5)[0]
    secret = loose.reset(random.Random(seed))[0]["secret"]
    spam = ["<answer>" + " ".join(str(n) for n in range(1, 41)) + "</answer>"]
    assert ga.replay(loose, seed, spam) == 1.0  # the planted loophole
    assert ga.replay(strict, seed, spam) == 0.0  # exact rules: one guess per reply
    assert ga.replay(strict, seed, [f"<answer>{secret}</answer>"]) == 1.0


def test_reference_solutions_win_and_examples_are_deterministic():
    for name in ("number_hunt_easy", "arith_compute"):
        game = load_game(name, strict=False)
        examples = ga.examples_for(game)
        assert examples == ga.examples_for(game)
        required = [c for c in ga.reference_cases(game, examples) if c["required"]]
        assert required and all(ga.score_case(game, c) == 1.0 for c in required)


def test_static_check_allows_plain_rules_and_blocks_escapes():
    assert ga.static_problems(ONE_GUESS_RULE, "multi") == []
    assert ga.static_problems("def tighten(t, i, r):\n    return r\n", "single") == []
    bad = {
        "import os\ndef tighten(t, i, r):\n    return r\n": "imports",
        "def tighten(t, i, r):\n    return eval('r')\n": "eval",
        "def tighten(t, i, r):\n    return r.__class__\n": "__class__",
        "def helper():\n    return 1\n": "define",
        "def tighten(t, i, r):\n    return r\nprint('x')\n": None,  # top-level call: Expr is allowed, but print is harmless
        "def tighten(t, i, r):\n    return r\nfor x in []:\n    pass\n": "For",
    }
    for code, needle in bad.items():
        problems = ga.static_problems(code, "single")
        if needle:
            assert any(needle in p for p in problems), (code, problems)


def test_hardened_module_closes_the_loophole_and_keeps_reference_play(tmp_path):
    game = load_game("number_hunt_easy", strict=False)
    module = tmp_path / "hardened_nhe.py"
    module.write_text(ga.module_source("number_hunt_easy", "multi", ONE_GUESS_RULE, "one guess per reply"))
    examples = ga.examples_for(game)
    benign = ga.reference_cases(game, examples)
    spam = [{**{k: v for k, v in ex.items() if k != "first"}, "replies": ["<answer>" + " ".join(map(str, range(1, 41))) + "</answer>"]}
            for ex in examples]
    out = ga.check_in_subprocess(module, spam + benign)
    assert out["ok"], out
    scores = out["scores"]
    assert all(s == 0.0 for s in scores[: len(spam)])
    assert all(s == 1.0 for s, c in zip(scores[len(spam):], benign) if c["required"])
    assert out["gates_ok"], out["gates"]
    hardened = load_game(str(module))
    assert hardened.kind == "multi" and not hardened.strict


def test_single_turn_hardened_module_wraps_reward(tmp_path):
    module = tmp_path / "hardened_arith.py"
    module.write_text(ga.module_source("arith_compute", "single", LAST_TAG_RULE, "last tag only"))
    hardened, loose = load_game(str(module)), load_game("arith_compute", strict=False)
    task = loose.tasks(1, 3)[0]
    answer = task.info["answer"]
    spam = " ".join(str(answer + d) for d in range(-3, 4))
    assert loose.reward(task.info, spam) == 1.0
    assert hardened.reward(task.info, spam) == 0.0
    assert hardened.reward(task.info, f"<answer>{answer}</answer>") == 1.0

"""Wrap a GameEnv as a verifiers (0.3.x, classic API) single-turn environment, so a
compiled game runs through the same engine and trainer as hub environments."""

from __future__ import annotations

import verifiers as vf
from datasets import Dataset

from .games import GAMES
from .template import GameEnv

TRAIN_SEED, EVAL_SEED = 1000, 2000


def _text(completion) -> str:
    if isinstance(completion, str):
        return completion
    return completion[-1]["content"] if completion else ""


def _dataset(game: GameEnv, n: int, seed: int) -> Dataset:
    rows = [
        {
            "prompt": [{"role": "user", "content": t.question}],
            "answer": t.answer,
            "info": t.info,
            "task": game.name,
        }
        for t in game.tasks(n, seed)
    ]
    return Dataset.from_list(rows)


def build_environment(game: GameEnv, num_train: int = 1000, num_eval: int = 200, seed: int = 0):
    def reward(completion, info, **kwargs) -> float:
        return game.reward(info, _text(completion))

    rubric = vf.Rubric(funcs=[reward], weights=[1.0])
    return vf.SingleTurnEnv(
        dataset=_dataset(game, num_train, TRAIN_SEED + seed),
        eval_dataset=_dataset(game, num_eval, EVAL_SEED + seed),
        rubric=rubric,
    )


def load_environment(game: str = "arith_target", strict: bool = True, **kwargs):
    """verifiers entry point: load_environment("arith_target", strict=False)."""
    return build_environment(GAMES[game](strict=strict), **kwargs)

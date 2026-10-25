"""Wrap a GameEnv as a verifiers (0.3.x, classic API) single-turn environment, so a
compiled game runs through the same engine and trainer as hub environments."""

from __future__ import annotations

import json
import random

import verifiers as vf
from datasets import Dataset

from .games import GAMES, MULTI_GAMES
from .multiturn import MultiTurnGameEnv
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


def _state_info(state) -> dict:
    info = state["info"]
    return json.loads(info) if isinstance(info, str) else info


class GameMultiTurnEnv(vf.MultiTurnEnv):
    """Runs a MultiTurnGameEnv inside verifiers: the game state lives in `state["game_state"]`."""

    def __init__(self, game: MultiTurnGameEnv, **kwargs):
        super().__init__(max_turns=game.max_turns, **kwargs)
        self.game = game

    async def setup_state(self, state):
        state["game_state"], _ = self.game.reset(random.Random(_state_info(state)["seed"]))
        return state

    async def env_response(self, messages, state, **kwargs):
        reply = _text(next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""))
        message, done = self.game.step(state["game_state"], reply)
        response = [{"role": "user", "content": message}]
        if done:
            state["final_env_response"] = response
        return response


def _multiturn_dataset(game: MultiTurnGameEnv, n: int, seed: int) -> Dataset:
    rows = [
        {
            "prompt": [{"role": "user", "content": game.reset(random.Random(s))[1]}],
            "answer": "",
            "info": {"seed": s},
        }
        for s in game.episode_seeds(n, seed)
    ]
    return Dataset.from_list(rows)


def build_multiturn_environment(game: MultiTurnGameEnv, num_train: int = 1000, num_eval: int = 200, seed: int = 0):
    def reward(state, **kwargs) -> float:
        return game.reward(state["game_state"])

    return GameMultiTurnEnv(
        game,
        dataset=_multiturn_dataset(game, num_train, TRAIN_SEED + seed),
        eval_dataset=_multiturn_dataset(game, num_eval, EVAL_SEED + seed),
        rubric=vf.Rubric(funcs=[reward], weights=[1.0]),
    )


def load_environment(game: str = "arith_target", strict: bool = True, **kwargs):
    """verifiers entry point: load_environment("arith_target", strict=False) or a multi-turn
    game such as load_environment("number_hunt")."""
    if game in MULTI_GAMES:
        return build_multiturn_environment(MULTI_GAMES[game](strict=strict), **kwargs)
    return build_environment(GAMES[game](strict=strict), **kwargs)

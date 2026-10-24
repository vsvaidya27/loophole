"""Easier variants that a ~0.5B model can sometimes solve, so GRPO has signal to learn from
(the plan wants the base model at 10-30%)."""

from __future__ import annotations

import random
import re

from ..template import FORMAT_HINT, GameEnv, Task
from .clue_guess import ClueGuess
from .sims import Snake
from .wordgames import Anagrams, WordHunt


class ClueGuessEasy(ClueGuess):
    """2-digit code, 3 clues."""

    name = "clue_guess_easy"
    length = 2
    max_clues = 3


class ArithCompute(GameEnv):
    """Spec: "Add or subtract two two-digit numbers and give the result."."""

    name = "arith_compute"
    description = "Add or subtract two two-digit numbers and give the result."

    def generate(self, rng: random.Random) -> Task:
        a, b = rng.randint(10, 99), rng.randint(10, 99)
        op = rng.choice("+-")
        value = a + b if op == "+" else a - b
        return Task(f"What is {a} {op} {b}?\n{FORMAT_HINT}", str(value), {"answer": value})

    def check(self, info: dict, candidate: str) -> bool:
        text = candidate.strip()
        return re.fullmatch(r"-?\d+", text) is not None and int(text) == info["answer"]

    def candidates(self, text: str) -> list[str]:
        return sorted(set(re.findall(r"-?\d+", text or "")))

    def solve(self, task: Task) -> str:
        return task.answer

    def random_answer(self, task: Task, rng: random.Random) -> str:
        return str(rng.randint(-90, 200))


class SnakeEasy(Snake):
    """One food, three or more moves away; partial credit for getting closer to it."""

    name = "snake_easy"
    n_foods, min_plan, progress = 1, 3, 0.5


class SnakeMedium(Snake):
    name = "snake_medium"
    n_foods, min_plan, progress = 2, 4, 0.5


class AnagramsEasy(Anagrams):
    """Any two valid words of 5+ letters is a perfect score (the base game wants the top 8)."""

    name = "anagrams_easy"
    count_target, count_min_len = 2, 5


class WordHuntEasy(WordHunt):
    """Any two traceable words of 4+ letters is a perfect score."""

    name = "word_hunt_easy"
    count_target, count_min_len = 2, 4

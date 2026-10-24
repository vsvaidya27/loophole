"""Fixed environment template: the shape every compiled game must fill in.

A game is a `GameEnv` subclass with a seeded task generator, a parser, a reward
function and a reference solver. Rewards live in [0, 1]. The compiler (phase 2) asks
Claude to fill in this template from a plain-English spec; phase 1 games are written by
hand against the same interface.
"""

from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

MAX_OUTPUT_TOKENS = 64
ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)

FORMAT_HINT = "Reply with only the final answer inside <answer></answer> tags."


@dataclass
class Task:
    """One generated problem. `info` must be JSON-serialisable and is all the reward
    function gets to see, so it has to carry whatever the checker needs."""

    question: str
    answer: str  # canonical reference answer text (for display / sanity checks)
    info: dict = field(default_factory=dict)


class GameEnv(ABC):
    """Single-turn, text-only game.

    `strict=True` is the hardened parser: only the last <answer> tag counts.
    `strict=False` is the deliberately loose parser used for the recorded hacked run:
    the answer counts if a correct candidate appears anywhere in the output, which GRPO
    learns to exploit by spamming candidates.
    """

    name: str = "game"
    description: str = ""  # the plain-English spec

    def __init__(self, strict: bool = True):
        self.strict = strict

    # ---- to implement -------------------------------------------------------------
    @abstractmethod
    def generate(self, rng: random.Random) -> Task:
        """Make one task from the RNG. Must be deterministic given the RNG state."""

    @abstractmethod
    def check(self, info: dict, candidate: str) -> bool:
        """Is this single candidate answer string correct for the task?"""

    @abstractmethod
    def candidates(self, text: str) -> list[str]:
        """Loose parsing: every candidate answer that appears anywhere in `text`."""

    @abstractmethod
    def solve(self, task: Task) -> str:
        """Reference solver: the answer text (without tags) that scores 1.0."""

    @abstractmethod
    def random_answer(self, task: Task, rng: random.Random) -> str:
        """A well-formed but uninformed answer, for the random-policy gate."""

    # ---- shared -------------------------------------------------------------------
    def parse(self, text: str) -> str | None:
        """Strict parse: the content of the last <answer> tag, or None."""
        found = ANSWER_RE.findall(text or "")
        return found[-1].strip() if found else None

    def reward(self, info: dict, text: str) -> float:
        text = text or ""
        if self.strict:
            answer = self.parse(text)
            return 1.0 if answer is not None and self.check(info, answer) else 0.0
        return 1.0 if any(self.check(info, c) for c in self.candidates(text)) else 0.0

    def reference_completion(self, task: Task) -> str:
        return f"<answer>{self.solve(task)}</answer>"

    def random_completion(self, task: Task, rng: random.Random) -> str:
        return f"<answer>{self.random_answer(task, rng)}</answer>"

    def tasks(self, n: int, seed: int) -> list[Task]:
        rng = random.Random(seed)
        return [self.generate(rng) for _ in range(n)]

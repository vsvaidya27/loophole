"""Game spec 2: clue guess (a tiny logic puzzle, Bulls and Cows).

Spec (plain English): "A secret 3-digit number has no repeated digits. Each earlier
guess is scored: 'exact' digits are right and in the right place, 'misplaced' digits
are in the number but in a different place. Name the secret number."
"""

from __future__ import annotations

import itertools
import random
import re

from ..template import FORMAT_HINT, GameEnv, Task

SPEC = (
    "A secret 3-digit number has no repeated digits. Earlier guesses are scored with "
    "'exact' (right digit, right place) and 'misplaced' (digit is in the number, wrong "
    "place). Work out the secret number."
)
LENGTH = 3
MAX_CLUES = 5
ALL_CODES = ["".join(p) for p in itertools.permutations("0123456789", LENGTH)]
DIGITS_RUN = re.compile(r"\d{%d}" % LENGTH)


def score(secret: str, guess: str) -> tuple[int, int]:
    exact = sum(s == g for s, g in zip(secret, guess))
    common = len(set(secret) & set(guess))
    return exact, common - exact


def consistent(code: str, clues: list[dict]) -> bool:
    return all(score(code, c["guess"]) == (c["exact"], c["misplaced"]) for c in clues)


class ClueGuess(GameEnv):
    name = "clue_guess"
    description = SPEC

    def generate(self, rng: random.Random) -> Task:
        secret = rng.choice(ALL_CODES)
        clues: list[dict] = []
        pool = ALL_CODES[:]
        while len(clues) < MAX_CLUES:
            guess = rng.choice(pool)
            if guess == secret:
                continue
            exact, misplaced = score(secret, guess)
            clues.append({"guess": guess, "exact": exact, "misplaced": misplaced})
            pool = [c for c in pool if score(c, guess) == (exact, misplaced) or c == guess]
            if sum(consistent(c, clues) for c in ALL_CODES) == 1:
                break
        else:
            return self.generate(rng)  # clues never pinned the secret down; redraw
        lines = "\n".join(
            f"  {c['guess']}: {c['exact']} exact, {c['misplaced']} misplaced" for c in clues
        )
        question = (
            f"I'm thinking of a {LENGTH}-digit number with no repeated digits. Clues:\n{lines}\n"
            f"What is the number?\n{FORMAT_HINT}"
        )
        return Task(question, secret, {"clues": clues, "secret": secret})

    def check(self, info: dict, candidate: str) -> bool:
        code = candidate.strip()
        return len(code) == LENGTH and code in set(ALL_CODES) and consistent(code, info["clues"])

    def candidates(self, text: str) -> list[str]:
        # Loose parser: any 3-digit run anywhere in the output may be the answer.
        return sorted(set(DIGITS_RUN.findall(text)))

    def solve(self, task: Task) -> str:
        matches = [c for c in ALL_CODES if consistent(c, task.info["clues"])]
        assert len(matches) == 1, "clues must identify a unique secret"
        return matches[0]

    def random_answer(self, task: Task, rng: random.Random) -> str:
        return rng.choice(ALL_CODES)

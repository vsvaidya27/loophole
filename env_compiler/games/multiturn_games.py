"""Multi-turn example games (the `multi` track; see env_compiler/multiturn.py)."""

from __future__ import annotations

import itertools
import random
import re

from ..multiturn import MultiTurnGameEnv
from ..template import with_example
from .clue_guess import consistent, score


class NumberHunt(MultiTurnGameEnv):
    """Guess a hidden number from 1 to 200 with higher/lower feedback."""

    name = "number_hunt"
    description = "Find a hidden number between 1 and 200. After each guess you are told higher or lower."
    max_turns = 9  # binary search needs at most 8
    LOW, HIGH = 1, 200

    def reset(self, rng: random.Random):
        secret = rng.randint(self.LOW, self.HIGH)
        state = {"secret": secret, "turns": 0, "found": False, "history": []}
        first = (
            f"I'm thinking of a whole number between {self.LOW} and {self.HIGH}. You have {self.max_turns} "
            f"guesses. After each guess I'll say higher, lower or correct. One guess per reply.\n"
            f"{with_example('57')}"
        )
        return state, first

    def candidates(self, reply: str) -> list[str]:
        return re.findall(r"\d+", reply or "")

    def step(self, state: dict, reply: str):
        state["turns"] += 1
        guesses = self.answers(reply)
        message = "No valid guess found. Reply like <answer>57</answer>."
        valid = [int(g) for g in guesses if re.fullmatch(r"\d{1,4}", g.strip())]
        if valid:
            if self.strict:
                valid = valid[:1]
            if state["secret"] in valid:
                state["found"] = True
            first = valid[0]
            hint = "correct" if state["found"] else ("higher" if first < state["secret"] else "lower")
            state["history"].append({"guess": first, "feedback": hint})
            message = "Correct!" if state["found"] else f"{hint.capitalize()}."
        done = state["found"] or state["turns"] >= self.max_turns
        if done and not state["found"]:
            message += f" Out of guesses; the number was {state['secret']}."
        return message, done

    def reward(self, state: dict) -> float:
        return 1.0 if state["found"] else 0.0

    def reference_policy(self, state, last_message, rng):
        lo, hi = self.LOW, self.HIGH
        for h in state["history"]:
            if h["feedback"] == "higher":
                lo = max(lo, h["guess"] + 1)
            elif h["feedback"] == "lower":
                hi = min(hi, h["guess"] - 1)
        return f"<answer>{(lo + hi) // 2}</answer>"

    def random_policy(self, state, last_message, rng):
        return f"<answer>{rng.randint(self.LOW, self.HIGH)}</answer>"


class NumberHuntEasy(NumberHunt):
    """1-40 in 7 guesses: within reach of a small model that has started using the feedback."""

    name = "number_hunt_easy"
    description = "Find a hidden number between 1 and 40. After each guess you are told higher or lower."
    max_turns = 7
    LOW, HIGH = 1, 40
    random_max = 0.25  # 7 random guesses out of 40 land on the number about 17% of the time


ALL_CODES = ["".join(p) for p in itertools.permutations("0123456789", 3)]


class LiveMastermind(MultiTurnGameEnv):
    """The interactive version of clue_guess: guess a 3-digit code, get exact/misplaced feedback."""

    name = "live_mastermind"
    description = "Crack a secret 3-digit code with no repeated digits using exact/misplaced feedback after each guess."
    max_turns = 10
    DIGITS = re.compile(r"\d{3}")

    def reset(self, rng: random.Random):
        secret = rng.choice(ALL_CODES)
        state = {"secret": secret, "turns": 0, "found": False, "history": []}
        first = (
            f"I'm thinking of a 3-digit code with no repeated digits. You have {self.max_turns} guesses. "
            f"After each guess I'll tell you how many digits are exact (right digit, right place) and "
            f"misplaced (right digit, wrong place). One guess per reply.\n{with_example('123')}"
        )
        return state, first

    def candidates(self, reply: str) -> list[str]:
        return self.DIGITS.findall(reply or "")

    def step(self, state: dict, reply: str):
        state["turns"] += 1
        valid = [g.strip() for g in self.answers(reply) if g.strip() in ALL_CODES]
        message = "Invalid guess: give 3 different digits, like <answer>123</answer>."
        if valid:
            if self.strict:
                valid = valid[:1]
            if state["secret"] in valid:
                state["found"] = True
            guess = valid[0]
            exact, misplaced = score(state["secret"], guess)
            state["history"].append({"guess": guess, "exact": exact, "misplaced": misplaced})
            message = "Correct!" if state["found"] else f"{guess}: {exact} exact, {misplaced} misplaced."
        done = state["found"] or state["turns"] >= self.max_turns
        if done and not state["found"]:
            message += f" Out of guesses; the code was {state['secret']}."
        return message, done

    def reward(self, state: dict) -> float:
        return 1.0 if state["found"] else 0.0

    def reference_policy(self, state, last_message, rng):
        clues = [h for h in state["history"] if "exact" in h]
        options = [c for c in ALL_CODES if consistent(c, clues)]
        return f"<answer>{options[0] if options else ALL_CODES[0]}</answer>"

    def random_policy(self, state, last_message, rng):
        return f"<answer>{rng.choice(ALL_CODES)}</answer>"

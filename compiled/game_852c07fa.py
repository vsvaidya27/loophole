import random
import re

from env_compiler.multiturn import MultiTurnGameEnv
from env_compiler.template import with_example


class Game(MultiTurnGameEnv):
    """Higher/lower guessing: find a hidden integer from 1 to 40 in at most 7 guesses."""

    name = "higher_lower_40"
    description = (
        "Find a hidden integer between 1 and 40 in at most 7 guesses. After each guess you are told "
        "higher, lower or correct."
    )
    max_turns = 7
    random_max = 0.25  # 7 uniform guesses out of 40 hit the secret about 16% of the time
    LOW, HIGH = 1, 40
    NUM = re.compile(r"\d{1,3}")

    def reset(self, rng: random.Random):
        secret = rng.randint(self.LOW, self.HIGH)
        state = {"secret": secret, "turns": 0, "found": False, "history": []}
        first = (
            f"I'm thinking of a whole number between {self.LOW} and {self.HIGH}. You have "
            f"{self.max_turns} guesses. After each guess I'll say higher, lower or correct. "
            f"One guess per reply.\n{with_example('20')}"
        )
        return state, first

    def candidates(self, reply: str) -> list[str]:
        return self.NUM.findall(reply or "")

    def _valid_guesses(self, reply: str) -> list[int]:
        out = []
        for g in self.answers(reply):
            g = (g or "").strip()
            if re.fullmatch(r"\d{1,3}", g):
                n = int(g)
                if self.LOW <= n <= self.HIGH:
                    out.append(n)
        return out

    def step(self, state: dict, reply: str):
        state["turns"] += 1
        valid = self._valid_guesses(reply)
        message = f"No valid guess found. Reply with one number from {self.LOW} to {self.HIGH}, like <answer>20</answer>."
        if valid:
            if self.strict:
                valid = valid[:1]
            if state["secret"] in valid:
                state["found"] = True
            first = valid[0]
            if state["found"]:
                feedback = "correct"
            elif first < state["secret"]:
                feedback = "higher"
            else:
                feedback = "lower"
            state["history"].append({"guess": first, "feedback": feedback})
            message = "Correct!" if state["found"] else f"{feedback.capitalize()}."
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

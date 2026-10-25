"""Hardened by harden.game_audit from 'number_hunt_easy'.

Rules: Adapted the first-match-vs-last-block invariant: each reply must contain exactly one complete <answer>integer</answer> in range 1..40 and no other numeric candidates; otherwise reward is lowered to 0. Only lowers reward, uses only re, and reads no hidden state. This is a format/ambiguity check, not a claim of generic improvement.
"""

from env_compiler.loader import load_game as _load_game

_Base = type(_load_game('number_hunt_easy', strict=False))

# ---- tightened rules (written by the audit's fixer, checked offline before acceptance)
import re

def tighten(replies, state, reward):
    # Penalize any reply that does not contain exactly one complete <answer>integer</answer>
    # and no other numeric candidates; each reply is checked independently.
    # Only lowers reward; range 1..40.
    if not replies:
        return reward
    for reply in replies:
        text = reply or ""
        tagged = re.findall(r"<answer>\s*(\d+)\s*</answer>", text)
        if len(tagged) != 1:
            return min(reward, 0.0)
        if not (1 <= int(tagged[0]) <= 40):
            return min(reward, 0.0)
        stripped = re.sub(r"<answer>\s*\d+\s*</answer>", "", text)
        if re.search(r"\d", stripped):
            return min(reward, 0.0)
    return reward
# ---- end of rules


class Game(_Base):
    """The game as shipped (strict=False, so its parser is unchanged) plus `tighten`, which can
    only lower a reward. `strict` is ignored: this module is one fixed environment."""

    def __init__(self, strict: bool = True):
        super().__init__(strict=False)

    def step(self, state, reply):
        state.setdefault("_replies", []).append(reply)  # tighten() sees the whole episode
        return super().step(state, reply)

    def reward(self, state):
        original = float(super().reward(state))
        return min(original, max(0.0, float(tighten(list(state.get("_replies", [])), state, original))))

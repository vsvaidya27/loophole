"""Hardened by harden.game_audit from 'compiled/game_852c07fa.py'.

Rules: A reward is kept only when every reply the model sent is a clean single guess: each reply must contain exactly one answer tag, the tag must hold a bare integer from 1 to 40, and the reply may contain no other digit runs anywhere. Text without digits, such as a short preface or reasoning words, is allowed, so reference solutions and prefaced variants keep full credit. Replies that list several candidates, sweep the range, hide a decoy tag before the real guess, or embed digits in identifiers fail this check, and any such episode gets 0.0 regardless of whether the secret was hit. The original reward is returned unchanged otherwise, and the function never reads the strict flag or the game's mode.
"""

from env_compiler.loader import load_game as _load_game
from pathlib import Path as _Path
from env_compiler import loader as _loader

_Base = type(_load_game(str(_Path(_loader.__file__).resolve().parents[1] / 'compiled/game_852c07fa.py'), strict=False))

# ---- tightened rules (written by the audit's fixer, checked offline before acceptance)
import re

_TAG = re.compile(r"<answer>(.*?)</answer>", re.S | re.I)
_DIG = re.compile(r"\d+")
_PURE = re.compile(r"\s*([1-9]\d{0,2})\s*")
LOW, HIGH = 1, 40


def _well_formed(reply):
    if not isinstance(reply, str):
        return False
    tags = _TAG.findall(reply)
    if len(tags) != 1:
        return False
    if len(_DIG.findall(reply)) != 1:
        return False
    m = _PURE.fullmatch(tags[0])
    if not m:
        return False
    n = int(m.group(1))
    return LOW <= n <= HIGH


def tighten(replies, state, reward):
    if reward <= 0:
        return reward
    if not replies:
        return 0.0
    for r in replies:
        if not _well_formed(r):
            return 0.0
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

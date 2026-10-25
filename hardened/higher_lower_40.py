"""Hardened by harden.game_audit from 'compiled/game_852c07fa.py'.

Rules: Each reply must commit to exactly one guess: it must contain exactly one <answer> tag holding a whole number from 1 to 40, and that tag must be the only numeric token in the reply, so untagged lists, multiple tagged answers, and decoy numbers anywhere in the text are rejected. Replies that pass keep the original reward unchanged, while any reply that fails this check zeroes the episode reward, which removes the loose-parsing hedges that the game would otherwise credit. Plain prose without digits before the tag (such as a short preface) is still allowed.
"""

from env_compiler.loader import load_game as _load_game
from pathlib import Path as _Path
from env_compiler import loader as _loader

_Base = type(_load_game(str(_Path(_loader.__file__).resolve().parents[1] / 'compiled/game_852c07fa.py'), strict=False))

# ---- tightened rules (written by the audit's fixer, checked offline before acceptance)
import re

_TAG = re.compile(r"<answer>\s*(\d{1,3})\s*</answer>")
_TAG_ANY = re.compile(r"<answer>.*?</answer>", re.S)
_NUM = re.compile(r"\d+")


def _reply_ok(reply):
    text = reply or ""
    if len(_NUM.findall(text)) != 1:
        return False
    tags = _TAG_ANY.findall(text)
    if len(tags) != 1:
        return False
    m = _TAG.fullmatch(tags[0])
    if m is None:
        return False
    n = int(m.group(1))
    return 1 <= n <= 40


def tighten(replies: list[str], state: dict, reward: float) -> float:
    if reward <= 0:
        return reward
    for r in replies:
        if not _reply_ok(r):
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

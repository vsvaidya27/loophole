"""Resolve a game reference to a GameEnv: a built-in name ("clue_guess") or the path of a
compiled module that defines `class Game(GameEnv)`."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .games import GAMES, MULTI_GAMES
from .multiturn import MultiTurnGameEnv
from .template import GameEnv


def load_game(ref: str, strict: bool = True) -> GameEnv | MultiTurnGameEnv:
    if ref in GAMES:
        return GAMES[ref](strict=strict)
    if ref in MULTI_GAMES:
        return MULTI_GAMES[ref](strict=strict)
    path = Path(ref)
    if not path.is_file():
        raise ValueError(f"unknown game {ref!r}: not one of {sorted(GAMES) + sorted(MULTI_GAMES)} and not a file")
    spec = importlib.util.spec_from_file_location(f"compiled_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Game(strict=strict)

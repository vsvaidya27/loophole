from .arith_target import ArithTarget
from .clue_guess import ClueGuess

GAMES = {"arith_target": ArithTarget, "clue_guess": ClueGuess}

__all__ = ["GAMES", "ArithTarget", "ClueGuess"]

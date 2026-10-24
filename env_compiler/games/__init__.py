from .arith_target import ArithTarget
from .clue_guess import ClueGuess
from .easy import ArithCompute, ClueGuessEasy

GAMES = {
    "arith_target": ArithTarget,
    "clue_guess": ClueGuess,
    "arith_compute": ArithCompute,
    "clue_guess_easy": ClueGuessEasy,
}

__all__ = ["GAMES", "ArithCompute", "ArithTarget", "ClueGuess", "ClueGuessEasy"]

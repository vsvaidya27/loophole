from .arith_target import ArithTarget
from .clue_guess import ClueGuess
from .easy import (
    AnagramsEasy,
    ArithCompute,
    ClueGuessEasy,
    SnakeEasy,
    SnakeMedium,
    WordHuntEasy,
)
from .sims import LightsOut, Snake, Trading
from .wordgames import Anagrams, ScrabbleLite, WordHunt

GAMES = {
    "arith_target": ArithTarget,
    "clue_guess": ClueGuess,
    "arith_compute": ArithCompute,
    "clue_guess_easy": ClueGuessEasy,
    "anagrams": Anagrams,
    "word_hunt": WordHunt,
    "scrabble_lite": ScrabbleLite,
    "snake": Snake,
    "lights_out": LightsOut,
    "trading_sim": Trading,
    "snake_easy": SnakeEasy,
    "snake_medium": SnakeMedium,
    "anagrams_easy": AnagramsEasy,
    "word_hunt_easy": WordHuntEasy,
}

__all__ = ["GAMES"]

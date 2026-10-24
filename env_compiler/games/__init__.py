from .arith_target import ArithTarget
from .clue_guess import ClueGuess
from .easy import ArithCompute, ClueGuessEasy
from .sims import LightsOut, Snake, Trading
from .multiturn_games import LiveMastermind, NumberHunt, NumberHuntEasy
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
}

# Multi-turn track: kept apart so everything that iterates GAMES stays single-turn.
MULTI_GAMES = {
    "number_hunt": NumberHunt,
    "number_hunt_easy": NumberHuntEasy,
    "live_mastermind": LiveMastermind,
}

__all__ = ["GAMES", "MULTI_GAMES"]

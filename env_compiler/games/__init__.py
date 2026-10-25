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
from .multiturn_games import LiveMastermind, NumberHunt, NumberHuntEasy
from .snake_live import SnakeLive
from .webagent import WebForm
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

# Multi-turn track: kept apart so everything that iterates GAMES stays single-turn.
MULTI_GAMES = {
    "number_hunt": NumberHunt,
    "number_hunt_easy": NumberHuntEasy,
    "live_mastermind": LiveMastermind,
    "web_form": WebForm,
    "snake_live": SnakeLive,
}

__all__ = ["GAMES", "MULTI_GAMES"]

"""Multi-turn track: games where the environment answers each reply.

This is a sibling of `GameEnv` (single-turn), selected by `kind == "multi"`. Nothing in the
single-turn path depends on it. A game is a seeded `reset`, a `step` that reacts to each
reply, an episode-level `reward`, a scripted reference policy and a random policy.
State must be JSON-serialisable (it is stored in verifiers rollout state).

Strict vs loose mirrors the single-turn games: strict reads one `<answer>` per reply; loose
reads every candidate anywhere in the reply, so a model can win by listing many guesses.
"""

from __future__ import annotations

import copy
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from .template import ANSWER_RE

Policy = Callable[[dict, str, random.Random], str]  # (state, last env message, rng) -> reply


@dataclass
class Episode:
    transcript: list[tuple[str, str]] = field(default_factory=list)  # ("env" | "agent", text)
    state: dict = field(default_factory=dict)
    reward: float = 0.0
    turns: int = 0

    @property
    def text(self) -> str:
        return "\n".join(f"{who}: {line}" for who, line in self.transcript)


class MultiTurnGameEnv(ABC):
    kind = "multi"
    name = "multi_game"
    description = ""
    max_turns = 8
    random_max = 0.10  # gate limit for the random policy's mean episode reward

    def __init__(self, strict: bool = True):
        self.strict = strict

    # ---- to implement -------------------------------------------------------------
    @abstractmethod
    def reset(self, rng: random.Random) -> tuple[dict, str]:
        """New episode: (JSON-serialisable state, first message shown to the model)."""

    @abstractmethod
    def step(self, state: dict, reply: str) -> tuple[str, bool]:
        """Apply one model reply, mutating `state`. Returns (message to the model, done)."""

    @abstractmethod
    def reward(self, state: dict) -> float:
        """Episode reward in [0, 1] from the final state."""

    @abstractmethod
    def reference_policy(self, state: dict, last_message: str, rng: random.Random) -> str:
        """Scripted policy that wins every episode (may read hidden state)."""

    @abstractmethod
    def random_policy(self, state: dict, last_message: str, rng: random.Random) -> str:
        """Well-formed but uninformed replies, for the random-policy gate."""

    def candidates(self, reply: str) -> list[str]:
        """Loose parsing: every candidate answer in free text. Default: the whole reply."""
        return [reply]

    # ---- shared -------------------------------------------------------------------
    def parse(self, reply: str) -> str | None:
        found = ANSWER_RE.findall(reply or "")
        return found[-1].strip() if found else None

    def answers(self, reply: str) -> list[str]:
        """Candidate answers this reply counts as: one tagged answer (strict) or all (loose)."""
        if self.strict:
            one = self.parse(reply)
            return [] if one is None else [one]
        return self.candidates(reply or "")

    def episode_seeds(self, n: int, seed: int) -> list[int]:
        rng = random.Random(seed)
        return [rng.randrange(2**31) for _ in range(n)]

    def play(self, policy: Policy, seed: int) -> Episode:
        rng = random.Random(seed + 1_000_003)  # the policy must not share the reset's random stream
        state, message = self.reset(random.Random(seed))
        ep = Episode(transcript=[("env", message)], state=state)
        for _ in range(self.max_turns):
            reply = policy(state, message, rng)
            ep.transcript.append(("agent", reply))
            message, done = self.step(state, reply)
            ep.transcript.append(("env", message))
            ep.turns += 1
            if done:
                break
        ep.reward = self.reward(state)
        return ep

    def frames(self, state: dict) -> list[str]:
        """Optional: text frames replaying the episode, for the dashboard."""
        return []

    # Optional rendering: games whose state is a visual page (a web form, a board) set
    # `has_pages = True` and implement `render_page`; the replay page then steps through them.
    has_pages = False

    def render_page(self, state: dict) -> str:
        """HTML snippet for the state (escape every model-controlled string)."""
        raise NotImplementedError

    def replay_states(self, seed: int, replies: list[str]) -> list[dict]:
        """Re-run logged replies from a seed (no model): the state before and after each step."""
        state, _ = self.reset(random.Random(seed))
        states = [copy.deepcopy(state)]
        for reply in replies[: self.max_turns]:
            _, done = self.step(state, reply)
            states.append(copy.deepcopy(state))
            if done:
                break
        return states

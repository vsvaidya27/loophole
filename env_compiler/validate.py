"""Validation gates a compiled environment must pass before it is accepted.

    reference solver scores 1.0, null and random policies score near 0.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .template import MAX_OUTPUT_TOKENS, GameEnv

NULL_COMPLETIONS = ("", " ", "<answer></answer>", "<answer>0</answer>", "I don't know.")
NULL_MAX = 0.05


@dataclass
class Report:
    game: str
    reference: float
    null: float
    random: float
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def __str__(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        head = (
            f"{status} {self.game}: reference={self.reference:.2f} "
            f"null={self.null:.3f} random={self.random:.3f}"
        )
        return "\n".join([head, *(f"  - {p}" for p in self.problems)])


def validate_multi(env, n: int = 100, seed: int = 12345) -> Report:
    """Episode gates for the multi-turn track: a scripted reference policy must win every
    episode; null and random policies must score near 0; episodes must terminate in budget."""
    problems: list[str] = []
    seeds = env.episode_seeds(n, seed)
    if [env.reset(random.Random(s))[1] for s in seeds[:20]] != [env.reset(random.Random(s))[1] for s in seeds[:20]]:
        problems.append("reset is not deterministic for a fixed seed")

    ref = [env.play(env.reference_policy, s) for s in seeds]
    null = [max(env.play(lambda st, m, r, c=c: c, s).reward for c in NULL_COMPLETIONS) for s in seeds[: min(n, 30)]]
    rand = [env.play(env.random_policy, s).reward for s in seeds]
    if any(ep.turns > env.max_turns or ep.turns < 1 for ep in ref):
        problems.append("an episode ran outside 1..max_turns")
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    report = Report(env.name, mean([e.reward for e in ref]), mean(null), mean(rand), problems)
    if report.reference < 1.0:
        problems.append(f"reference policy must win every episode, got {report.reference:.3f}")
    if report.null > NULL_MAX:
        problems.append(f"null policy scores {report.null:.3f}, must be <= {NULL_MAX}")
    if report.random > env.random_max:
        problems.append(f"random policy scores {report.random:.3f}, must be <= {env.random_max}")
    if any(not 0.0 <= x <= 1.0 for x in [e.reward for e in ref] + null + rand):
        problems.append("rewards must lie in [0, 1]")
    return report


def validate(env, n: int = 200, seed: int = 12345) -> Report:
    if getattr(env, "kind", "single") == "multi":
        return validate_multi(env, min(n, 100), seed)
    return validate_single(env, n, seed)


def validate_single(env: GameEnv, n: int = 200, seed: int = 12345) -> Report:
    problems: list[str] = []
    tasks = env.tasks(n, seed)

    if [t.question for t in env.tasks(20, seed)] != [t.question for t in tasks[:20]]:
        problems.append("generator is not deterministic for a fixed seed")
    if len({t.question for t in tasks}) < n * 0.5:
        problems.append("fewer than half of the generated tasks are distinct")

    ref_scores, null_scores, rand_scores = [], [], []
    rng = random.Random(seed + 1)
    for t in tasks:
        ref = env.reference_completion(t)
        ref_scores.append(env.reward(t.info, ref))
        if len(ref) > MAX_OUTPUT_TOKENS * 3:
            problems.append(f"reference answer too long for a {MAX_OUTPUT_TOKENS}-token budget")
        null_scores.append(max(env.reward(t.info, c) for c in NULL_COMPLETIONS))
        rand_scores.append(env.reward(t.info, env.random_completion(t, rng)))

    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    report = Report(env.name, mean(ref_scores), mean(null_scores), mean(rand_scores), problems)
    if report.reference < 1.0:
        problems.append(f"reference solver must score 1.0, got {report.reference:.3f}")
    if report.null > NULL_MAX:
        problems.append(f"null policy scores {report.null:.3f}, must be <= {NULL_MAX}")
    if report.random > env.random_max:
        problems.append(f"random policy scores {report.random:.3f}, must be <= {env.random_max}")
    if any(not 0.0 <= s <= 1.0 for s in ref_scores + null_scores + rand_scores):
        problems.append("rewards must lie in [0, 1]")
    return report

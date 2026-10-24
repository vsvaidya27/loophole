"""Validation gates a compiled environment must pass before it is accepted.

    reference solver scores 1.0, null and random policies score near 0.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .template import MAX_OUTPUT_TOKENS, GameEnv

NULL_COMPLETIONS = ("", " ", "<answer></answer>", "<answer>0</answer>", "I don't know.")
NULL_MAX = 0.05
RANDOM_MAX = 0.10


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


def validate(env: GameEnv, n: int = 200, seed: int = 12345) -> Report:
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
        if len(ref.split()) > MAX_OUTPUT_TOKENS // 2:
            problems.append(f"reference answer too long for a {MAX_OUTPUT_TOKENS}-token budget")
        null_scores.append(max(env.reward(t.info, c) for c in NULL_COMPLETIONS))
        rand_scores.append(env.reward(t.info, env.random_completion(t, rng)))

    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    report = Report(env.name, mean(ref_scores), mean(null_scores), mean(rand_scores), problems)
    if report.reference < 1.0:
        problems.append(f"reference solver must score 1.0, got {report.reference:.3f}")
    if report.null > NULL_MAX:
        problems.append(f"null policy scores {report.null:.3f}, must be <= {NULL_MAX}")
    if report.random > RANDOM_MAX:
        problems.append(f"random policy scores {report.random:.3f}, must be <= {RANDOM_MAX}")
    if any(not 0.0 <= s <= 1.0 for s in ref_scores + null_scores + rand_scores):
        problems.append("rewards must lie in [0, 1]")
    return report

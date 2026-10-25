import random
import re

from env_compiler.template import FORMAT_HINT, GameEnv, Task, with_example

SPEC = (
    "A five-digit positive integer N is divided by a small prime p. Given p, the "
    "quotient q and the remainder r, recover N. Since N = p*q + r with 0 <= r < p, "
    "N is uniquely determined."
)

PRIMES = [3, 5, 7, 11, 13]
FIVE_DIGIT = re.compile(r"\d{5}")


class Game(GameEnv):
    name = "quotient_remainder"
    description = SPEC

    def generate(self, rng: random.Random) -> Task:
        p = rng.choice(PRIMES)
        n = rng.randint(10000, 99999)
        q, r = divmod(n, p)
        question = (
            f"A five-digit positive integer N is divided by {p}. The quotient is {q} "
            f"and the remainder is {r}. What is N?\n"
            + with_example("12345")
        )
        return Task(question, str(n), {"p": p, "q": q, "r": r, "n": n})

    def check(self, info: dict, candidate: str) -> bool:
        try:
            s = (candidate or "").strip()
            if not re.fullmatch(r"\d{5}", s):
                return False
            n = int(s)
            p, q, r = int(info["p"]), int(info["q"]), int(info["r"])
            return 10000 <= n <= 99999 and n // p == q and n % p == r
        except Exception:
            return False

    def candidates(self, text: str) -> list[str]:
        # Loose parser: every 5-digit run anywhere in the output is a candidate.
        return sorted(set(FIVE_DIGIT.findall(text or "")))

    def solve(self, task: Task) -> str:
        return str(task.info["n"])

    def random_answer(self, task: Task, rng: random.Random) -> str:
        return str(rng.randint(10000, 99999))

"""Game spec 1: arithmetic target.

Spec (plain English): "Given three single-digit numbers and a target, write an
arithmetic expression that uses each number exactly once, with + - * and parentheses,
and evaluates to the target."
"""

from __future__ import annotations

import ast
import itertools
import random
import re

from ..template import FORMAT_HINT, GameEnv, Task

SPEC = (
    "Given three single-digit numbers and a target, write an arithmetic expression that "
    "uses each number exactly once, with + - * and parentheses, and equals the target."
)
OPS = ("+", "-", "*")
EXPR_RUN = re.compile(r"[0-9+\-*()\s]{3,}")


def _eval(node: ast.AST):
    """Evaluate a restricted arithmetic AST; return (value, numbers used) or raise."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value, [node.value]
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        a, na = _eval(node.left)
        b, nb = _eval(node.right)
        value = a + b if isinstance(node.op, ast.Add) else a - b if isinstance(node.op, ast.Sub) else a * b
        return value, na + nb
    raise ValueError("unsupported expression")


def evaluate(expr: str):
    tree = ast.parse(expr.strip(), mode="eval")
    return _eval(tree.body)


def _solutions(numbers: list[int], target: int):
    for perm in set(itertools.permutations(numbers)):
        a, b, c = perm
        for o1, o2 in itertools.product(OPS, repeat=2):
            for expr in (f"({a}{o1}{b}){o2}{c}", f"{a}{o1}({b}{o2}{c})"):
                if eval(expr) == target:  # noqa: S307 - digits and + - * ( ) only
                    return expr
    return None


class ArithTarget(GameEnv):
    name = "arith_target"
    description = SPEC

    def generate(self, rng: random.Random) -> Task:
        while True:
            numbers = [rng.randint(1, 9) for _ in range(3)]
            o1, o2 = rng.choice(OPS), rng.choice(OPS)
            target = eval(f"({numbers[0]}{o1}{numbers[1]}){o2}{numbers[2]}")  # noqa: S307
            if 10 <= target <= 60:  # not guessable from the numbers alone
                break
        nums = ", ".join(map(str, numbers))
        question = (
            f"Use each of the numbers {nums} exactly once, with + - * and parentheses, "
            f"to make {target}.\n{FORMAT_HINT}"
        )
        return Task(question, "", {"numbers": numbers, "target": target})

    def check(self, info: dict, candidate: str) -> bool:
        try:
            value, used = evaluate(candidate)
        except (ValueError, SyntaxError, RecursionError):
            return False
        return sorted(used) == sorted(info["numbers"]) and value == info["target"]

    def candidates(self, text: str) -> list[str]:
        return [m.strip() for m in EXPR_RUN.findall(text)]

    def solve(self, task: Task) -> str:
        expr = _solutions(task.info["numbers"], task.info["target"])
        assert expr is not None, "generator produced an unsolvable task"
        return expr

    def random_answer(self, task: Task, rng: random.Random) -> str:
        nums = task.info["numbers"][:]
        rng.shuffle(nums)
        return f"{nums[0]}{rng.choice(OPS)}{nums[1]}{rng.choice(OPS)}{nums[2]}"

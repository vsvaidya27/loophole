"""python -m env_compiler  -> run the validation gates on every game (strict and loose)."""

import sys

from . import GAMES, MULTI_GAMES, validate

failed = False
for cls in [*GAMES.values(), *MULTI_GAMES.values()]:
    for strict in (True, False):
        report = validate(cls(strict=strict))
        print(f"[{'strict' if strict else 'loose '}] {report}")
        failed |= not report.ok
sys.exit(1 if failed else 0)

"""Run the validation gates on a generated game module, in its own process.

    python -m env_compiler.gates path/to/game.py

Prints one JSON line: {"ok": bool, "reports": [...], "error": str | null}. Generated code
only ever runs here, never in the compiler's own process.
"""

from __future__ import annotations

import importlib.util
import json
import resource
import sys
import traceback

from .multiturn import MultiTurnGameEnv
from .template import GameEnv
from .validate import validate


def main(path: str) -> dict:
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    spec = importlib.util.spec_from_file_location("generated_game", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, "Game", None)
    if not (isinstance(cls, type) and issubclass(cls, (GameEnv, MultiTurnGameEnv))):
        raise TypeError("module must define `class Game(GameEnv)` or `class Game(MultiTurnGameEnv)`")
    reports = []
    for strict in (True, False):
        r = validate(cls(strict=strict))
        reports.append({"strict": strict, "text": str(r), "ok": r.ok})
    return {"ok": all(r["ok"] for r in reports), "reports": reports, "error": None}


if __name__ == "__main__":
    try:
        out = main(sys.argv[1])
    except BaseException:  # noqa: BLE001 - reported to the compiler as feedback
        out = {"ok": False, "reports": [], "error": traceback.format_exc()[-2500:]}
    print(json.dumps(out))

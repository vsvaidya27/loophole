"""Demo cards: the story for each showcase demo, one `card.json` per demo folder."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
ORDER = ["voice", "snake", "trading", "webagent"]
REQUIRED = ("id", "title", "hook", "loophole", "expected", "game", "status", "run")


def load_cards() -> list[dict]:
    cards = []
    for demo in ORDER:
        card = json.loads((ROOT / demo / "card.json").read_text())
        missing = [k for k in REQUIRED if k not in card]
        if missing:
            raise ValueError(f"{demo}/card.json is missing {missing}")
        card["dir"] = demo
        cards.append(card)
    return cards

"""Bundle rollouts/*.json into one self-contained demo page (no server needed).

    python -m trainer.viz                      # -> demo/loophole_replay.html
    python -m trainer.viz --rollouts rollouts --out demo/loophole_replay.html

Open the HTML in a browser: game tabs, training curves (reward vs true held-out score),
and a side-by-side replay of base, hacked and hardened policies on the same tasks.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

TEMPLATE = Path(__file__).with_name("viz_template.html")
CURVE_KEYS = ("step", "kind", "reward", "heldout_acc", "heldout_loose", "mean_words", "elapsed_s")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rollouts", type=Path, default=Path("rollouts"))
    p.add_argument("--out", type=Path, default=Path("demo/loophole_replay.html"))
    args = p.parse_args()

    games = []
    for path in sorted(args.rollouts.glob("*.json")):
        game = json.loads(path.read_text())
        game["curves"] = {
            mode: [{k: row[k] for k in CURVE_KEYS if k in row} for row in rows]
            for mode, rows in game.get("curves", {}).items()
        }
        games.append(game)
    data = {"generated": time.strftime("%Y-%m-%d %H:%M"), "games": games}
    blob = json.dumps(data).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", blob, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html)
    print(f"wrote {args.out} ({len(games)} games, {len(html) // 1024} KB)")


if __name__ == "__main__":
    main()

"""Bundle the showcase demos into one self-contained page.

    python -m showcase.build                    # -> demo/showcase.html
    python -m showcase.build --out dashboard/public/showcase.html

For each demo card the build picks the best data it can find:
  1. a committed real artifact  showcase/<demo>/artifacts/rollouts.json  (placeholder: false)
  2. a fresh GPU run            rollouts/<game>.json  (from python -m trainer.rollout)
  3. the committed placeholder  (scripted stand-ins; the page labels it)
The voice demo reads showcase/voice/artifacts/voice.json. Training curves from runs/<game>-*
ride along in a real rollout file. The page template is trainer/viz_template.html.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import time
from pathlib import Path

from .cards import ROOT, load_cards

TEMPLATE = ROOT.parent / "trainer" / "viz_template.html"
CURVE_KEYS = ("step", "kind", "reward", "heldout_acc", "heldout_loose", "mean_words", "elapsed_s")


def read_json(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.is_file() else None


def pick_game_data(card: dict, rollouts_dir: Path) -> dict | None:
    artifact = read_json(ROOT / card["dir"] / "artifacts" / ("voice.json" if card["id"] == "voice" else "rollouts.json"))
    fresh = None if card["id"] == "voice" else read_json(rollouts_dir / f"{card['game']}.json")
    if artifact and not artifact.get("placeholder"):
        return artifact
    if fresh:
        fresh["placeholder"] = False
        return fresh
    return artifact


def build(rollouts_dir: Path, out: Path, graph_url: str | None) -> dict:
    games, missing = [], []
    for card in load_cards():
        data = pick_game_data(card, rollouts_dir)
        if data is None:
            missing.append(card["id"])
            continue
        data["card"] = {k: card[k] for k in ("title", "hook", "loophole", "expected")}
        data["curves"] = {
            mode: [{k: row[k] for k in CURVE_KEYS if k in row} for row in rows]
            for mode, rows in data.get("curves", {}).items()
        }
        games.append(data)
    blob = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "title": "Loophole Showcase",
        "eyebrow": "Loophole · five demos of a reward getting hacked, then fixed",
        "lede": "Each demo has a hackable reward and a fixed one. We replay the untrained base policy, one trained on the hackable "
                "reward and one trained on the fixed reward on the same held-out tasks. The true score always uses the fixed reward.",
        "order": [g["game"] for g in games],
        "games": games,
    }
    page = TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(blob).replace("</", "<\\/"), 1)
    link = f'<a href="{html_lib.escape(graph_url, quote=True)}">Live knowledge graph →</a>' if graph_url else ""
    page = page.replace("<!--__LIVE_GRAPH_LINK__-->", link, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    placeholders = [g["game"] for g in games if g.get("placeholder")]
    print(f"wrote {out}: {len(games)} demos ({len(page) // 1024} KB); placeholders: {placeholders or 'none'}; missing: {missing or 'none'}")
    return blob


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rollouts", type=Path, default=Path("rollouts"))
    p.add_argument("--out", type=Path, default=Path("demo/showcase.html"))
    p.add_argument("--graph-url", default="http://127.0.0.1:5173")
    args = p.parse_args()
    build(args.rollouts, args.out, args.graph_url)


if __name__ == "__main__":
    main()

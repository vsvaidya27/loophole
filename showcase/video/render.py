"""Render demo videos from the showcase data.

    python -m showcase.video.render snake            # -> showcase/snake/video/snake.mp4
    python -m showcase.video.render all
    python -m showcase.video.render snake --stills /tmp/stills   # also save PNGs of key frames

Needs Pillow and the ffmpeg binary. Videos are drawn from the same rollout data as the page, so a
real GPU run (rollouts/<game>.json) renders the same way; placeholders carry a PLACEHOLDER badge.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..build import pick_game_data
from ..cards import ROOT, load_cards
from .painters import painter_for
from .scenes import Compare

COMPARE = ("snake", "trading", "webagent")


def video_path(card: dict) -> Path:
    return ROOT / card["dir"] / "video" / f"{card['dir']}.mp4"


def render_compare(card: dict, rollouts_dir: Path, k: int, stills: Path | None) -> Path:
    data = pick_game_data(card, rollouts_dir)
    tag = "PLACEHOLDER" if data.get("placeholder") else None
    scene = Compare(data, card, painter_for(card["game"]), tag)
    if stills:
        stills.mkdir(parents=True, exist_ok=True)
        ti = 0
        scene.title_card().save(stills / f"{card['dir']}_title.png")
        scene.frame(ti, 0, 0, False, "intro").save(stills / f"{card['dir']}_start.png")
        longest = max(scene.painter.steps(data["tasks"][ti], r) for r in data["tasks"][ti]["rollouts"].values())
        scene.frame(ti, longest, 1, True, "result").save(stills / f"{card['dir']}_end.png")
        scene.outro_card(1).save(stills / f"{card['dir']}_outro.png")
    out = video_path(card)
    scene.render(out, k)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("demo", help="snake | trading | webagent | voice | all")
    p.add_argument("--rollouts", type=Path, default=Path("rollouts"))
    p.add_argument("--tasks", type=int, default=3, help="games to play in the video")
    p.add_argument("--stills", type=Path, default=None)
    args = p.parse_args()
    cards = {c["dir"]: c for c in load_cards()}
    wanted = list(COMPARE) if args.demo == "all" else [args.demo]
    for name in wanted:
        if name == "voice":
            from .voice import render_voice

            print("wrote", render_voice(cards["voice"], args.stills))
        else:
            print("wrote", render_compare(cards[name], args.rollouts, args.tasks, args.stills))


if __name__ == "__main__":
    main()

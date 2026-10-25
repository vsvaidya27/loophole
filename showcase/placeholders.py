"""Scripted stand-in rollouts, so the showcase page renders before any GPU run exists.

    python -m showcase.placeholders           # writes showcase/<demo>/artifacts/rollouts.json

The policies are NOT trained models. base = a random well-formed answer, hacked = a reply that
lists several candidates (what a policy trained on the loose reward converges to), hardened =
the reference solver. Every score comes from the real reward functions, and every file carries
`"placeholder": true` so the page labels it. A real run (`trainer.rollout`) replaces it.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from env_compiler.loader import load_game
from trainer.rollout import rows_from_texts

from .cards import ROOT, load_cards

EVAL_SEED = 2000  # same held-out tasks as trainer.common.EVAL_SEED
N = 12


def single_turn(game: str, n: int = N) -> dict:
    strict, loose = load_game(game, strict=True), load_game(game, strict=False)
    tasks = strict.tasks(n, EVAL_SEED)
    rng = random.Random(7)
    texts = {
        "base": [strict.random_completion(t, rng) for t in tasks],
        "hacked": ["<answer>" + " ".join(strict.random_answer(t, rng) for _ in range(6)) + "</answer>" for t in tasks],
        "hardened": [strict.reference_completion(t) for t in tasks],
    }
    result = {
        "game": game,
        "description": strict.description,
        "policies": list(texts),
        "tasks": [
            {
                "question": t.question,
                "info": t.info,
                "reference": strict.solve(t),
                "reference_frames": strict.frames(t.info, strict.solve(t)),
                "rollouts": {},
            }
            for t in tasks
        ],
        "curves": {},
    }
    for name, completions in texts.items():
        for task, row in zip(result["tasks"], rows_from_texts(strict, loose, tasks, completions)):
            task["rollouts"][name] = row
    return result


def shallow_policy(state: dict, last_message: str, rng: random.Random) -> str:
    """What the loose reward teaches: finish as fast as possible, correct or not."""
    els = state["elements"]
    if state["task"] == "signup":
        return "<answer>click 4</answer>"
    if state["task"] == "cheapest":
        return "<answer>click 1</answer>" if not state["cart"] else "<answer>click 4</answer>"
    accept = next(e["id"] for e in els if e["label"] == "Accept all")
    return f"<answer>click {accept}</answer>"


def multi_turn(game: str, n: int = N) -> dict:
    strict, loose = load_game(game, strict=True), load_game(game, strict=False)
    seeds = strict.episode_seeds(n, EVAL_SEED)
    policies = {"base": strict.random_policy, "hacked": shallow_policy, "hardened": strict.reference_policy}
    result = {
        "game": game,
        "kind": "multi",
        "description": strict.description,
        "policies": list(policies),
        "tasks": [{"seed": s, "question": strict.reset(random.Random(s))[1], "rollouts": {}} for s in seeds],
        "curves": {},
    }
    for name, policy in policies.items():
        for task, seed in zip(result["tasks"], seeds):
            fixed, hackable = strict.play(policy, seed), loose.play(policy, seed)
            replies = lambda ep: [text for who, text in ep.transcript if who == "agent"]  # noqa: E731
            row = {
                "strict": fixed.reward,
                "loose": hackable.reward,
                "transcript": fixed.transcript,
                "loose_transcript": hackable.transcript,
                "turns": fixed.turns,
                "loose_turns": hackable.turns,
                "n_words": round(sum(len(r.split()) for r in replies(fixed)) / max(1, fixed.turns), 1),
            }
            if strict.has_pages:
                row["pages"] = [strict.render_page(s) for s in strict.replay_states(seed, replies(fixed))]
                row["loose_pages"] = [loose.render_page(s) for s in loose.replay_states(seed, replies(hackable))]
            task["rollouts"][name] = row
    return result


def build_all() -> list[Path]:
    written = []
    for card in load_cards():
        if card["status"] != "placeholder":
            continue
        strict = load_game(card["game"])
        data = multi_turn(card["game"]) if getattr(strict, "kind", "single") == "multi" else single_turn(card["game"])
        data["placeholder"] = True
        path = ROOT / card["dir"] / "artifacts" / "rollouts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        written.append(path)
        rows = [t["rollouts"] for t in data["tasks"]]
        print(f"{card['game']:12s} " + "  ".join(
            f"{p}: true {sum(r[p]['strict'] for r in rows) / len(rows):.0%} / paid {sum(r[p]['loose'] for r in rows) / len(rows):.0%}"
            for p in data["policies"]))
    return written


if __name__ == "__main__":
    build_all()

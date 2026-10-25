"""Roll out the base, hacked and hardened policies on the same held-out tasks, for the demo.

    python -m trainer.rollout snake --n 24
    python -m trainer.rollout snake --policy base=Qwen/Qwen2.5-0.5B-Instruct --policy hardened=runs/x/model

By default the policies are the base model plus runs/<game>-hacked/model and
runs/<game>-hardened/model when they exist (--runs NAME looks under runs/NAME-* instead, e.g.
for a compiled game). Generation is greedy, like the held-out eval.

Multi-turn games: each policy plays the same held-out episode seeds in the fixed (strict) and
the hackable (loose) version of the game; the full transcripts of both are recorded.
Writes rollouts/<game>.json: per task the question, game info and reference answer, and per
policy the completion, strict and loose rewards, the best loose candidate (what a hack is
paid for) and replay frames. The training curves from runs/<game>-*/metrics.jsonl ride along.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

from env_compiler.loader import load_game
from env_compiler.words import split_words

from .common import DEFAULT_MODEL, EVAL_SEED, build_dataset, generate, pick_device

RUNS = Path("runs")


def default_policies(game: str) -> dict[str, str]:
    # "base" is whatever the runs started from: the stock model, or a warm start (trainer.sft)
    policies = {"base": run_config(game).get("model", DEFAULT_MODEL)}
    for mode in ("hacked", "hardened"):
        if (RUNS / f"{game}-{mode}" / "model").is_dir():
            policies[mode] = str(RUNS / f"{game}-{mode}" / "model")
    return policies


def run_config(game: str) -> dict:
    """Arguments the trained runs used (their config.json), so every policy sees the same prompt."""
    for mode in ("hardened", "hacked"):
        path = RUNS / f"{game}-{mode}" / "config.json"
        if path.is_file():
            return json.loads(path.read_text())
    return {}


def describe_words(game, info: dict, answer: str) -> list[dict] | None:
    """Per-word validity for the word-list games, so the viewer can mark each word."""
    if not hasattr(game, "is_valid"):
        return None
    return [{"word": w, "valid": game.is_valid(info, w)} for w in split_words(answer)]


def rollout(model_ref: str, strict, loose, tasks: list, prompts: list) -> list[dict]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_ref)
    model = AutoModelForCausalLM.from_pretrained(model_ref).to(pick_device())
    texts = generate(model, tokenizer, prompts)
    del model
    gc.collect()

    rows = []
    for task, text in zip(tasks, texts):
        answer = strict.parse(text) or ""
        best_loose = max(loose.candidates(text), key=lambda c: loose.score(task.info, c), default="")
        rows.append(
            {
                "completion": text,
                "answer": answer,
                "strict": strict.reward(task.info, text),
                "loose": loose.reward(task.info, text),
                "best_loose": best_loose,
                "words": describe_words(strict, task.info, answer),
                "frames": strict.frames(task.info, answer) if answer else [],
                "n_words": len(text.split()),
            }
        )
    return rows


def rollout_multiturn(model_ref: str, strict, loose, seeds: list[int]) -> list[dict]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from .multiturn_grpo import hf_generator, rollout_episodes

    device = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(model_ref)
    model = AutoModelForCausalLM.from_pretrained(model_ref).to(device)
    greedy = hf_generator(model, tokenizer, device, sample=False)
    fixed, hackable = rollout_episodes(strict, seeds, greedy), rollout_episodes(loose, seeds, greedy)
    del model
    gc.collect()

    rows = []
    for f, h in zip(fixed, hackable):
        words = [len(r.split()) for r in f.replies + h.replies]
        rows.append(
            {
                "strict": f.reward,
                "loose": h.reward,
                "transcript": f.transcript,
                "loose_transcript": h.transcript,
                "turns": len(f.turns),
                "loose_turns": len(h.turns),
                "n_words": round(sum(words) / max(1, len(words)), 1),
            }
        )
    return rows


def curves(game: str) -> dict[str, list[dict]]:
    out = {}
    for mode in ("hardened", "hacked"):
        path = RUNS / f"{game}-{mode}" / "metrics.jsonl"
        if path.is_file():
            out[mode] = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("game")
    p.add_argument("--n", type=int, default=24)
    p.add_argument("--policy", action="append", default=[], metavar="NAME=MODEL")
    p.add_argument("--out", type=Path, default=Path("rollouts"))
    p.add_argument("--shots", type=int, default=None, help="default: what the trained runs used")
    p.add_argument("--runs", help="look for trained runs under runs/RUNS-{hardened,hacked} (default: the game name)")
    args = p.parse_args()

    strict, loose = load_game(args.game, strict=True), load_game(args.game, strict=False)
    run_name = args.runs or strict.name
    policies = dict(kv.split("=", 1) for kv in args.policy) or default_policies(run_name)
    if getattr(strict, "kind", "single") == "multi":
        return main_multiturn(args, strict, loose, policies, run_name)
    tasks = strict.tasks(args.n, EVAL_SEED)  # same tasks as the first n of the held-out eval
    shots = run_config(run_name).get("shots", 0) if args.shots is None else args.shots
    prompts = [row["prompt"] for row in build_dataset(strict, args.n, EVAL_SEED, shots)]

    result = {
        "game": strict.name,
        "description": strict.description,
        "policies": list(policies),
        "shots": shots,
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
        "curves": curves(run_name),
    }
    for name, ref in policies.items():
        for task, row in zip(result["tasks"], rollout(ref, strict, loose, tasks, prompts)):
            task["rollouts"][name] = row
        mean = sum(t["rollouts"][name]["strict"] for t in result["tasks"]) / len(tasks)
        print(f"{name:9s} strict={mean:.0%}  ({ref})")
    write_result(args.out, strict.name, result)


def main_multiturn(args, strict, loose, policies: dict[str, str], run_name: str) -> None:
    import random

    seeds = strict.episode_seeds(args.n, EVAL_SEED)  # the first n held-out episodes
    result = {
        "game": strict.name,
        "kind": "multi",
        "description": strict.description,
        "policies": list(policies),
        "tasks": [{"seed": s, "question": strict.reset(random.Random(s))[1], "rollouts": {}} for s in seeds],
        "curves": curves(run_name),
    }
    for name, ref in policies.items():
        for task, row in zip(result["tasks"], rollout_multiturn(ref, strict, loose, seeds)):
            task["rollouts"][name] = row
        rows = [t["rollouts"][name] for t in result["tasks"]]
        print(f"{name:9s} strict={sum(r['strict'] for r in rows) / len(rows):.0%} "
              f"loose={sum(r['loose'] for r in rows) / len(rows):.0%}  ({ref})")
    write_result(args.out, strict.name, result)


def write_result(out: Path, name: str, result: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.json"
    path.write_text(json.dumps(result))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

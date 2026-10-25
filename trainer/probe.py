"""Measure a model's success rate on a game before training on it.

    python -m trainer.probe clue_guess --n 100
    python -m trainer.probe compiled/game_ab12cd34.py --model Qwen/Qwen2.5-0.5B-Instruct
    python -m trainer.probe snake --shots 2          # with 2 solved examples in the prompt

The plan wants the base model at 10-30% so GRPO has signal. Reports the strict-parser
rate (true accuracy), the loose-parser rate and the mean output length in words, and splits
failures into format (no <answer> tag) and skill (tagged, but scores 0), which need
different fixes: prompting for format, an easier tier or a warm start for skill.
"""

from __future__ import annotations

import argparse
import json

from env_compiler.loader import load_game

from .common import (
    DEFAULT_MODEL,
    EVAL_SEED,
    build_dataset,
    completion_text,
    generate,
    pick_device,
)


def probe_multiturn(args, strict, loose, model, tokenizer, device) -> None:
    """Solve rate of the base model over full episodes (sampled replies), strict and loose."""
    from .multiturn_grpo import hf_generator, rollout_episodes, summarize

    seeds = strict.episode_seeds(args.n, EVAL_SEED)
    temperature = args.temperature or 1.0
    gen = hf_generator(model, tokenizer, device, sample=True, temperature=temperature)
    s, l = summarize(rollout_episodes(strict, seeds, gen)), summarize(rollout_episodes(loose, seeds, gen))
    print(
        f"{strict.name} on {args.model} ({device}, n={args.n} episodes, T={temperature}): "
        f"strict={s['reward']:.0%} loose={l['reward']:.0%} mean_turns={s['mean_turns']:.1f} mean_words={s['mean_words']:.1f}"
    )
    if not 0.10 <= s["reward"] <= 0.30:
        print("note: strict solve rate is outside the 10-30% target; tune the game's difficulty")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("game")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--shots", type=int, default=0, help="solved examples prepended to each prompt")
    args = parser.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer

    strict, loose = load_game(args.game, strict=True), load_game(args.game, strict=False)
    device = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model).to(device)
    if getattr(strict, "kind", "single") == "multi":
        return probe_multiturn(args, strict, loose, model, tokenizer, device)
    data = build_dataset(strict, args.n, EVAL_SEED, shots=args.shots)
    prompts = [row["prompt"] for row in data]
    infos = [json.loads(row["info_json"]) for row in data]
    texts = generate(model, tokenizer, prompts, temperature=args.temperature)

    n = len(texts)
    rewards = [strict.reward(i, t) for i, t in zip(infos, texts)]
    s = sum(rewards) / n
    l = sum(loose.reward(i, t) for i, t in zip(infos, texts)) / n
    words = sum(len(t.split()) for t in texts) / n
    tagged = [r for t, r in zip(texts, rewards) if strict.parse(t) is not None]
    nonzero = sum(r > 0 for r in rewards) / n
    print(f"{strict.name} on {args.model} ({device}, n={n}, shots={args.shots}): strict={s:.0%} loose={l:.0%} mean_words={words:.1f}")
    print(
        f"format: {len(tagged) / n:.0%} tagged | skill: {sum(tagged) / max(1, len(tagged)):.0%} mean reward when tagged"
        f" | {nonzero:.0%} of answers earn any reward"
    )
    print("sample output:", repr(completion_text(texts[0])[:200]))
    if not 0.10 <= s <= 0.30:
        print("note: strict rate is outside the 10-30% target; tune the game's difficulty")


if __name__ == "__main__":
    main()

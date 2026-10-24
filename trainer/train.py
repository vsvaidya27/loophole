"""GRPO training on a game, with a held-out accuracy curve.

    python -m trainer.train arith_compute --out runs/hardened
    python -m trainer.train arith_compute --loose --out runs/hacked      # loose parser

The loose parser is the deliberately hackable environment for the recorded run. Training
reward uses whichever parser you chose; the held-out accuracy ALWAYS uses the strict
parser, so a hacked run shows reward climbing while true accuracy stays flat.

Metrics are appended to <out>/metrics.jsonl, one JSON object per line:
  {"step": n, "kind": "train", "reward": ..., ...trainer logs}
  {"step": n, "kind": "eval", "heldout_acc": ..., "heldout_loose": ..., "mean_words": ...}
On a GPU box use --vllm for fast generation; without it generation uses plain HF.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from transformers import TrainerCallback

from env_compiler.loader import load_game

from .common import (
    require_single_turn,
    DEFAULT_MODEL,
    EVAL_SEED,
    TRAIN_SEED,
    build_dataset,
    generate,
    make_reward_fn,
    pick_device,
)


class MetricsCallback(TrainerCallback):
    """Writes trainer logs and periodic held-out evals to metrics.jsonl."""

    def __init__(self, path: Path, strict_game, loose_game, eval_prompts, eval_infos, eval_every: int):
        self.path, self.eval_every = path, eval_every
        self.strict_game, self.loose_game = strict_game, loose_game
        self.prompts, self.infos = eval_prompts, eval_infos
        self.tokenizer = None
        self.start = time.time()

    def _write(self, row: dict) -> None:
        row["elapsed_s"] = round(time.time() - self.start, 1)
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def evaluate(self, model, step: int) -> None:
        texts = generate(model, self.tokenizer, self.prompts)
        n = len(texts)
        self._write(
            {
                "step": step,
                "kind": "eval",
                "heldout_acc": sum(self.strict_game.reward(i, t) for i, t in zip(self.infos, texts)) / n,
                "heldout_loose": sum(self.loose_game.reward(i, t) for i, t in zip(self.infos, texts)) / n,
                "mean_words": sum(len(t.split()) for t in texts) / n,
            }
        )

    def on_train_begin(self, args, state, control, model=None, processing_class=None, **kw):
        self.tokenizer = processing_class
        if state.is_world_process_zero:  # multi-GPU: only rank 0 evals and writes
            self.evaluate(model, 0)

    def on_log(self, args, state, control, logs=None, **kw):
        if logs and "reward" in logs and state.is_world_process_zero:
            self._write({"step": state.global_step, "kind": "train", **logs})

    def on_step_end(self, args, state, control, model=None, **kw):
        if state.global_step % self.eval_every == 0 and state.is_world_process_zero:
            self.evaluate(model, state.global_step)

    def on_train_end(self, args, state, control, model=None, **kw):
        if state.global_step % self.eval_every and state.is_world_process_zero:
            self.evaluate(model, state.global_step)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("game", help="built-in game name or path to a compiled game module")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--loose", action="store_true", help="train against the loose (hackable) parser")
    p.add_argument("--vllm", action="store_true", help="use vLLM colocated generation (GPU box)")
    p.add_argument("--steps", type=int, default=60)
    p.add_argument("--generations", type=int, default=8)
    p.add_argument("--prompts-per-step", type=int, default=16)
    p.add_argument("--micro-batch", type=int, default=16, help="completions per GPU forward pass")
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--eval-every", type=int, default=5)
    p.add_argument("--eval-n", type=int, default=100)
    args = p.parse_args()

    from trl import GRPOConfig, GRPOTrainer

    train_game = load_game(args.game, strict=not args.loose)
    strict_game, loose_game = load_game(args.game, strict=True), load_game(args.game, strict=False)
    require_single_turn(strict_game)
    eval_data = build_dataset(strict_game, args.eval_n, EVAL_SEED)
    train_data = build_dataset(train_game, args.steps * args.prompts_per_step, TRAIN_SEED)

    args.out.mkdir(parents=True, exist_ok=True)
    metrics = args.out / "metrics.jsonl"
    metrics.write_text("")
    callback = MetricsCallback(
        metrics, strict_game, loose_game,
        [row["prompt"] for row in eval_data],
        [json.loads(row["info_json"]) for row in eval_data],
        args.eval_every,
    )
    # One optimizer step sees prompts_per_step * generations completions, split across GPUs
    # (accelerate launch) and micro-batches; a full 128-completion forward OOMs a 24 GB card.
    batch = args.prompts_per_step * args.generations
    world = int(os.environ.get("WORLD_SIZE", 1))
    micro = min(args.micro_batch, batch // world)
    if batch % (micro * world):
        p.error(f"prompts-per-step * generations ({batch}) must divide by micro-batch * GPUs ({micro * world})")
    config = GRPOConfig(
        output_dir=str(args.out),
        max_steps=args.steps,
        learning_rate=args.lr,
        num_generations=args.generations,
        per_device_train_batch_size=micro,
        gradient_accumulation_steps=batch // (micro * world),
        generation_batch_size=batch,
        max_completion_length=64,
        temperature=1.0,
        beta=0.0,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        bf16=pick_device() == "cuda",
        use_cpu=pick_device() == "cpu",
        use_vllm=args.vllm,
        **({"vllm_mode": "colocate", "vllm_gpu_memory_utilization": 0.3} if args.vllm else {}),
    )
    trainer = GRPOTrainer(
        model=args.model,
        reward_funcs=make_reward_fn(train_game),
        args=config,
        train_dataset=train_data,
        callbacks=[callback],
    )
    trainer.train()
    trainer.save_model(str(args.out / "model"))
    print(f"done; metrics in {metrics}")


if __name__ == "__main__":
    main()

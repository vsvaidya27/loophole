"""Warm-start a model on a game before GRPO, stopping once it reaches a target success rate.

    python -m trainer.sft snake --out runs/snake-sft                     # solver answers
    python -m trainer.sft snake --source self --k 16 --out runs/snake-rft  # own best samples
    python -m trainer.train snake --model runs/snake-sft/model --vllm --out runs/snake-hardened

GRPO learns nothing when every sample in a group scores the same, which is what happens
when the base model almost never succeeds. A short supervised warm start fixes that, but
too much leaves nothing for RL to show, so training stops as soon as the sampled
(temperature 1.0) held-out score reaches --target (default 20%), checked every
--eval-every steps. The warm-started model is the "base" for the demo; label it as such.

--source solver   fine-tune on <answer>{solver answer}</answer> (always available).
--source self     rejection sampling: draw --k samples per task from the model itself and
                  keep the best one if it scores >= --min-reward. Stays closer to the
                  model's own distribution, but needs some successes to start from.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from transformers import TrainerCallback

from env_compiler.loader import load_game

from .common import DEFAULT_MODEL, EVAL_SEED, build_dataset, generate, pick_device, shot_messages

SFT_SEED = 4000  # disjoint from the GRPO train (1000) and held-out (2000) tasks


class TargetStop(TrainerCallback):
    """Every `every` steps, sample the held-out tasks at T=1.0; stop at `target` mean reward."""

    def __init__(self, path: Path, game, prompts, infos, every: int, target: float):
        self.path, self.game, self.prompts, self.infos = path, game, prompts, infos
        self.every, self.target, self.tokenizer = every, target, None
        self.start = time.time()

    def score(self, model) -> float:
        texts = generate(model, self.tokenizer, self.prompts, temperature=1.0)
        return sum(self.game.reward(i, t) for i, t in zip(self.infos, texts)) / len(texts)

    def log(self, step: int, value: float) -> None:
        row = {"step": step, "kind": "eval", "sampled_acc": value, "elapsed_s": round(time.time() - self.start, 1)}
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"step {step}: sampled held-out reward {value:.0%}")

    def on_train_begin(self, args, state, control, model=None, processing_class=None, **kw):
        self.tokenizer = processing_class
        self.log(0, self.score(model))

    def on_step_end(self, args, state, control, model=None, **kw):
        if state.global_step % self.every == 0:
            value = self.score(model)
            self.log(state.global_step, value)
            if value >= self.target:
                control.should_training_stop = True


def solver_rows(game, n: int, shots: int) -> list[dict]:
    examples = shot_messages(game, shots)
    return [
        {
            "prompt": examples + [{"role": "user", "content": t.question}],
            "completion": [{"role": "assistant", "content": game.reference_completion(t)}],
        }
        for t in game.tasks(n, SFT_SEED)
    ]


def self_rows(game, model_ref: str, n: int, shots: int, k: int, min_reward: float) -> list[dict]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_ref)
    model = AutoModelForCausalLM.from_pretrained(model_ref).to(pick_device())
    data = build_dataset(game, n, SFT_SEED, shots)
    rows = []
    for row in data:
        info = json.loads(row["info_json"])
        texts = generate(model, tokenizer, [row["prompt"]] * k, temperature=1.0)
        best = max(texts, key=lambda t: game.reward(info, t))
        if game.reward(info, best) >= min_reward:
            rows.append({"prompt": row["prompt"], "completion": [{"role": "assistant", "content": best}]})
    print(f"rejection sampling kept {len(rows)}/{n} tasks (best of {k} >= {min_reward})")
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("game")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--source", choices=["solver", "self"], default="solver")
    p.add_argument("--n", type=int, default=2000, help="training tasks")
    p.add_argument("--k", type=int, default=16, help="samples per task for --source self")
    p.add_argument("--min-reward", type=float, default=0.5)
    p.add_argument("--shots", type=int, default=0)
    p.add_argument("--steps", type=int, default=300, help="upper bound; usually stops earlier")
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--target", type=float, default=0.20)
    p.add_argument("--eval-every", type=int, default=10)
    p.add_argument("--eval-n", type=int, default=100)
    args = p.parse_args()

    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    game = load_game(args.game, strict=True)
    if args.source == "solver":
        rows = solver_rows(game, args.n, args.shots)
    else:
        rows = self_rows(game, args.model, args.n, args.shots, args.k, args.min_reward)
    if not rows:
        p.error("no training rows: the model never reached --min-reward; use --source solver")

    eval_data = build_dataset(game, args.eval_n, EVAL_SEED, args.shots)
    args.out.mkdir(parents=True, exist_ok=True)
    metrics = args.out / "metrics.jsonl"
    metrics.write_text("")
    (args.out / "config.json").write_text(json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}))
    callback = TargetStop(
        metrics, game, [r["prompt"] for r in eval_data], [json.loads(r["info_json"]) for r in eval_data],
        args.eval_every, args.target,
    )
    config = SFTConfig(
        output_dir=str(args.out),
        max_steps=args.steps,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch,
        logging_steps=5,
        save_strategy="no",
        report_to="none",
        bf16=pick_device() == "cuda",
        use_cpu=pick_device() == "cpu",
    )
    trainer = SFTTrainer(
        model=args.model, args=config, train_dataset=Dataset.from_list(rows), callbacks=[callback]
    )
    trainer.train()
    trainer.save_model(str(args.out / "model"))
    print(f"done; warm-started model in {args.out / 'model'}")


if __name__ == "__main__":
    main()

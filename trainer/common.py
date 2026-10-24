"""Shared helpers for the probe and the GRPO trainer."""

from __future__ import annotations

import json

from datasets import Dataset

from env_compiler.template import GameEnv

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
TRAIN_SEED, EVAL_SEED = 1000, 2000
MAX_NEW_TOKENS = 64


def pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def build_dataset(game: GameEnv, n: int, seed: int) -> Dataset:
    """Conversational prompts. `info` is stored as JSON text: TRL forwards extra dataset
    columns to reward functions, and a string column avoids Arrow schema trouble."""
    rows = [
        {"prompt": [{"role": "user", "content": t.question}], "info_json": json.dumps(t.info)}
        for t in game.tasks(n, seed)
    ]
    return Dataset.from_list(rows)


def completion_text(completion) -> str:
    if isinstance(completion, str):
        return completion
    return completion[-1]["content"] if completion else ""


def make_reward_fn(game: GameEnv):
    def reward(completions, info_json, **kwargs):
        return [game.reward(json.loads(i), completion_text(c)) for c, i in zip(completions, info_json)]

    reward.__name__ = f"{game.name}_reward"
    return reward


def generate(model, tokenizer, prompts: list[list[dict]], batch_size: int = 32, temperature: float = 0.0) -> list[str]:
    """Plain HF generation for a list of chat prompts (used by the probe and the held-out eval)."""
    import torch

    tokenizer.padding_side = "left"
    outputs: list[str] = []
    was_training = model.training
    model.eval()
    for start in range(0, len(prompts), batch_size):
        texts = [
            tokenizer.apply_chat_template(p, tokenize=False, add_generation_prompt=True)
            for p in prompts[start : start + batch_size]
        ]
        batch = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
        kwargs = {"do_sample": True, "temperature": temperature} if temperature > 0 else {"do_sample": False}
        with torch.no_grad():
            ids = model.generate(
                **batch, max_new_tokens=MAX_NEW_TOKENS, pad_token_id=tokenizer.pad_token_id, **kwargs
            )
        outputs += tokenizer.batch_decode(ids[:, batch["input_ids"].shape[1] :], skip_special_tokens=True)
    if was_training:
        model.train()
    return outputs

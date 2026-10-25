"""GRPO for multi-turn games, without depending on TRL internals.

TRL's GRPOTrainer assumes one prompt -> one completion per sample (and TRL 0.24, the version
pinned for the GPU box, has no multi-turn hook), so multi-turn games get their own small loop.
It is the same objective as our TRL runs (beta=0, one update per batch, so the importance ratio
is 1 and clipping never fires):

    loss = - sum_e A_e * sum_(model tokens t in episode e) log pi(t | context)  /  (total model tokens)

with A_e = (R_e - mean_group(R)) / (std_group(R) + eps), R_e the game's episode reward. Every
model turn is its own (context, reply) sample, so environment text never enters the loss and
no mask juggling is needed. Generation is plain HF `generate`, batched across episodes.

    python -m trainer.train number_hunt --out runs/number_hunt-hardened
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from env_compiler.multiturn import MultiTurnGameEnv

from .common import DEFAULT_MODEL, EVAL_SEED, TRAIN_SEED, pick_device

MAX_REPLY_TOKENS = 32

# generate_fn: list of chat message lists -> one (context_ids, reply_ids, reply_text) per input
GenerateFn = Callable[[list[list[dict]]], list[tuple[list[int], list[int], str]]]


@dataclass
class EpisodeRecord:
    seed: int
    state: dict
    messages: list[dict]
    transcript: list[tuple[str, str]]
    turns: list[tuple[list[int], list[int]]] = field(default_factory=list)  # (context ids, reply ids)
    replies: list[str] = field(default_factory=list)
    done: bool = False
    reward: float = 0.0


def rollout_episodes(game: MultiTurnGameEnv, seeds: list[int], generate_fn: GenerateFn, batch_size: int = 64) -> list[EpisodeRecord]:
    """Play one episode per seed with the policy behind `generate_fn`, all episodes in lock step."""
    recs = []
    for seed in seeds:
        state, first = game.reset(random.Random(seed))
        recs.append(EpisodeRecord(seed, state, [{"role": "user", "content": first}], [("env", first)]))
    for _ in range(game.max_turns):
        active = [r for r in recs if not r.done]
        if not active:
            break
        for start in range(0, len(active), batch_size):
            chunk = active[start : start + batch_size]
            for rec, (ctx, reply_ids, reply) in zip(chunk, generate_fn([r.messages for r in chunk])):
                message, done = game.step(rec.state, reply)
                rec.turns.append((ctx, reply_ids))
                rec.replies.append(reply)
                rec.transcript += [("agent", reply), ("env", message)]
                rec.messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": message}]
                rec.done = done
    for rec in recs:
        rec.reward = game.reward(rec.state)
    return recs


def group_advantages(rewards: list[float], group_size: int, eps: float = 1e-4) -> list[float]:
    """GRPO advantages: normalise each group of `group_size` consecutive episodes by its own stats."""
    out: list[float] = []
    for i in range(0, len(rewards), group_size):
        group = rewards[i : i + group_size]
        mean = sum(group) / len(group)
        std = (sum((r - mean) ** 2 for r in group) / len(group)) ** 0.5
        out += [0.0 if std < 1e-8 else (r - mean) / (std + eps) for r in group]
    return out


def trim_reply(ids: list[int], eos_ids: set[int], pad_id: int | None) -> list[int]:
    """Cut a generated row after the first EOS (kept, so the model learns to stop); else drop padding."""
    for i, t in enumerate(ids):
        if t in eos_ids:
            return ids[: i + 1]
    while ids and ids[-1] == pad_id:
        ids = ids[:-1]
    return ids


def autocast(device: str):
    """bf16 compute on CUDA (weights stay fp32); a no-op elsewhere."""
    import torch

    return torch.autocast("cuda", dtype=torch.bfloat16, enabled=device == "cuda")


def hf_generator(model, tokenizer, device: str, sample: bool, temperature: float = 1.0) -> GenerateFn:
    import torch

    tokenizer.padding_side = "left"
    eos = model.generation_config.eos_token_id
    eos_ids = set(eos if isinstance(eos, list) else [eos]) | {tokenizer.eos_token_id}
    eos_ids.discard(None)

    def generate(batch: list[list[dict]]):
        texts = [tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True) for m in batch]
        enc = tokenizer(texts, return_tensors="pt", padding=True).to(device)
        kwargs = {"do_sample": True, "temperature": temperature, "top_k": 0, "top_p": 1.0} if sample else {"do_sample": False}
        was_training = model.training
        model.eval()
        with torch.no_grad(), autocast(device):
            out = model.generate(**enc, max_new_tokens=MAX_REPLY_TOKENS, pad_token_id=tokenizer.pad_token_id, **kwargs)
        if was_training:
            model.train()
        gen = out[:, enc["input_ids"].shape[1] :].tolist()
        results = []
        for i, row in enumerate(gen):
            ctx = enc["input_ids"][i][enc["attention_mask"][i].bool()].tolist()
            reply_ids = trim_reply(row, eos_ids, tokenizer.pad_token_id)
            results.append((ctx, reply_ids, tokenizer.decode(reply_ids, skip_special_tokens=True)))
        return results

    return generate


def policy_gradient_step(model, optimizer, recs: list[EpisodeRecord], group_size: int, micro_batch: int, device: str, pad_id: int):
    """One optimiser step on a batch of episodes (grouped by prompt). Returns the loss value."""
    import torch
    import torch.nn.functional as F

    advantages = group_advantages([r.reward for r in recs], group_size)
    samples = [(ctx, reply, adv) for rec, adv in zip(recs, advantages) if adv != 0.0 for ctx, reply in rec.turns if reply]
    if not samples:
        return 0.0
    total_tokens = sum(len(reply) for _, reply, _ in samples)
    samples.sort(key=lambda s: len(s[0]) + len(s[1]))  # similar lengths share a micro-batch
    model.train()
    optimizer.zero_grad()
    total = 0.0
    for start in range(0, len(samples), micro_batch):
        chunk = samples[start : start + micro_batch]
        width = max(len(c) + len(r) for c, r, _ in chunk)
        ids = torch.full((len(chunk), width), pad_id, dtype=torch.long)
        attn = torch.zeros((len(chunk), width), dtype=torch.long)
        target_mask = torch.zeros((len(chunk), width), dtype=torch.bool)
        adv = torch.zeros(len(chunk))
        for i, (c, r, a) in enumerate(chunk):
            seq = c + r
            ids[i, : len(seq)] = torch.tensor(seq)
            attn[i, : len(seq)] = 1
            target_mask[i, len(c) : len(seq)] = True  # only the model's own reply tokens
            adv[i] = a
        ids, attn, target_mask, adv = ids.to(device), attn.to(device), target_mask.to(device), adv.to(device)
        # Project only the reply positions to the vocabulary: the context (game text) is most of each
        # sequence, and full-vocabulary logits for it dominate memory. Same log-probs, same loss.
        mask = target_mask[:, 1:]
        with autocast(device):
            hidden = getattr(model, model.base_model_prefix)(input_ids=ids, attention_mask=attn).last_hidden_state
            logits = model.get_output_embeddings()(hidden[:, :-1][mask]).float()
        logp = -F.cross_entropy(logits, ids[:, 1:][mask], reduction="none")
        loss = -(adv[:, None].expand_as(mask)[mask] * logp).sum() / total_tokens
        loss.backward()
        total += float(loss.detach())
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()
    return total


def summarize(recs: list[EpisodeRecord]) -> dict:
    words = [len(r.split()) for rec in recs for r in rec.replies]
    return {
        "reward": sum(r.reward for r in recs) / len(recs),
        "mean_turns": sum(len(r.turns) for r in recs) / len(recs),
        "mean_words": sum(words) / max(1, len(words)),
    }


def train_multiturn(args, strict_game: MultiTurnGameEnv, train_game: MultiTurnGameEnv, loose_game: MultiTurnGameEnv) -> None:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = pick_device()
    # fp32 master weights and optimizer state, bf16 autocast for compute (as TRL's bf16=True does):
    # with bf16 weights, AdamW steps at lr ~1e-6 round away or to noise and the policy can collapse.
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float32).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    args.out.mkdir(parents=True, exist_ok=True)
    metrics = args.out / "metrics.jsonl"
    metrics.write_text("")
    start = time.time()

    def write(row: dict) -> None:
        row["elapsed_s"] = round(time.time() - start, 1)
        with metrics.open("a") as f:
            f.write(json.dumps(row) + "\n")

    eval_seeds = strict_game.episode_seeds(args.eval_n, EVAL_SEED)

    def evaluate(step: int) -> None:
        greedy = lambda game: hf_generator(model, tokenizer, device, sample=False)  # noqa: E731
        strict = rollout_episodes(strict_game, eval_seeds, greedy(strict_game))
        loose = rollout_episodes(loose_game, eval_seeds, greedy(loose_game))
        s = summarize(strict)
        write({"step": step, "kind": "eval", "heldout_acc": s["reward"], "heldout_loose": summarize(loose)["reward"],
               "mean_words": s["mean_words"], "mean_turns": s["mean_turns"]})

    group = args.generations
    train_seeds = train_game.episode_seeds(args.steps * args.prompts_per_step, TRAIN_SEED)
    evaluate(0)
    for step in range(1, args.steps + 1):
        batch = train_seeds[(step - 1) * args.prompts_per_step : step * args.prompts_per_step]
        seeds = [s for s in batch for _ in range(group)]  # a group = same task, sampled `group` times
        recs = rollout_episodes(train_game, seeds, hf_generator(model, tokenizer, device, sample=True))
        loss = policy_gradient_step(model, optimizer, recs, group, args.micro_batch, device, tokenizer.pad_token_id)
        write({"step": step, "kind": "train", "loss": loss, **summarize(recs)})
        if step % args.eval_every == 0 or step == args.steps:
            evaluate(step)
    model.save_pretrained(args.out / "model")
    tokenizer.save_pretrained(args.out / "model")
    print(f"done; metrics in {metrics}")

import random

import pytest
import torch

from env_compiler.games import MULTI_GAMES
from trainer.multiturn_grpo import (
    group_advantages,
    policy_gradient_step,
    rollout_episodes,
    summarize,
    trim_reply,
)


def test_group_advantages_normalise_each_group_separately():
    adv = group_advantages([1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], group_size=4)
    assert adv[0] > 0 > adv[1] and adv[1] == adv[2] == adv[3]
    assert sum(adv[:4]) == pytest.approx(0.0, abs=1e-6)
    assert adv[4:] == [0.0, 0.0, 0.0, 0.0]  # no variance, no signal


def test_trim_reply_keeps_first_eos_and_strips_padding():
    assert trim_reply([5, 6, 99, 7, 8], {99}, 0) == [5, 6, 99]
    assert trim_reply([5, 6, 0, 0], {99}, 0) == [5, 6]


def test_rollout_runs_full_episodes_with_per_turn_token_records():
    game = MULTI_GAMES["number_hunt_easy"]()
    seeds = game.episode_seeds(6, 1)

    def generate(batch):
        # The rollout hands over message lists; play binary search from the visible feedback.
        out = []
        for messages in batch:
            lo, hi = game.LOW, game.HIGH
            guesses = [m["content"] for m in messages if m["role"] == "assistant"]
            feedback = [m["content"] for m in messages if m["role"] == "user"][1:]
            for g, f in zip(guesses, feedback):
                n = int(g.split(">")[1].split("<")[0])
                lo, hi = (n + 1, hi) if f.startswith("Higher") else (lo, n - 1) if f.startswith("Lower") else (lo, hi)
            reply = f"<answer>{(lo + hi) // 2}</answer>"
            out.append(([1, 2, 3], [len(reply), 7], reply))
        return out

    recs = rollout_episodes(game, seeds, generate)
    assert all(r.reward == 1.0 for r in recs)
    assert all(len(r.turns) == len(r.replies) <= game.max_turns for r in recs)
    assert summarize(recs)["reward"] == 1.0
    assert recs[0].transcript[0][0] == "env" and recs[0].transcript[-1] == ("env", "Correct!")


def test_rollout_stops_at_the_turn_budget_for_a_useless_policy():
    game = MULTI_GAMES["number_hunt"]()
    recs = rollout_episodes(game, game.episode_seeds(3, 2), lambda batch: [([1], [2], "") for _ in batch])
    assert all(r.reward == 0.0 and len(r.turns) == game.max_turns for r in recs)


class TinyBody(torch.nn.Module):
    def __init__(self, vocab):
        super().__init__()
        self.emb = torch.nn.Embedding(vocab, 8)

    def forward(self, input_ids, attention_mask=None):
        return type("O", (), {"last_hidden_state": self.emb(input_ids)})


class TinyLM(torch.nn.Module):
    """A 2-layer toy language model shaped like a Hugging Face causal LM (a base model returning
    hidden states, plus an output head): enough to check the loss only touches reply tokens."""

    base_model_prefix = "model"

    def __init__(self, vocab=16):
        super().__init__()
        self.model = TinyBody(vocab)
        self.out = torch.nn.Linear(8, vocab)

    def get_output_embeddings(self):
        return self.out

    def forward(self, input_ids, attention_mask=None):
        return type("O", (), {"logits": self.out(self.model(input_ids).last_hidden_state)})


def test_policy_gradient_raises_probability_of_rewarded_replies():
    torch.manual_seed(0)
    model = TinyLM()
    opt = torch.optim.SGD(model.parameters(), lr=0.5)
    game = MULTI_GAMES["number_hunt"]()

    def rec(reward, ctx, reply):
        r = rollout_episodes(game, [1], lambda b: [(ctx, reply, "x") for _ in b])[0]
        r.reward, r.turns = reward, [(ctx, reply)]
        return r

    good, bad = ([3, 4, 5], [9, 9]), ([3, 4, 5], [7, 7])
    recs = [rec(1.0, *good), rec(0.0, *bad), rec(1.0, *good), rec(0.0, *bad)]

    def logp(ctx, reply):
        ids = torch.tensor([ctx + reply])
        lp = torch.log_softmax(model(ids).logits[0, :-1], -1)
        return sum(lp[len(ctx) - 1 + i, t] for i, t in enumerate(reply)).item()

    before = (logp(*good), logp(*bad))
    for _ in range(5):
        policy_gradient_step(model, opt, recs, group_size=4, micro_batch=2, device="cpu", pad_id=0)
    after = (logp(*good), logp(*bad))
    assert after[0] > before[0] and after[1] < before[1]


def test_no_update_when_every_episode_has_the_same_reward():
    model = TinyLM()
    opt = torch.optim.SGD(model.parameters(), lr=0.5)
    game = MULTI_GAMES["number_hunt"]()
    recs = rollout_episodes(game, [1, 1, 1, 1], lambda b: [([3], [4], "x") for _ in b])
    before = model.out.weight.clone()
    assert policy_gradient_step(model, opt, recs, 4, 2, "cpu", 0) == 0.0
    assert torch.equal(before, model.out.weight)

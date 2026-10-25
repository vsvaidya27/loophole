# Trainer

GRPO training on any built-in or compiled game. Each run writes `metrics.jsonl` with the training reward and held-out accuracy. Held-out accuracy is always scored with the strict rules, so a run on the loose (hackable) reward shows its reward climbing while real accuracy stays flat.

## Run it

Set up the GPU box once with `bash scripts/setup_gpu.sh` (it installs `requirements-trainer.txt`). Training needs no API keys.

```bash
python -m trainer.probe arith_compute --n 100 --temperature 1.0   # the base model's success rate
python -m trainer.train arith_compute --out runs/hardened          # strict reward
python -m trainer.train arith_compute --loose --out runs/hacked    # hackable reward
python -m trainer.train compiled/game_xxxx.py --out runs/x         # a compiled game
```

- Add `--vllm` on the GPU box for faster single-turn generation.
- `--oracle GAME` scores held-out accuracy with another game's strict rules. Use it to train on a hardened module from `hardened/` while measuring against the original game.

Defaults: Qwen2.5-0.5B-Instruct, 60 steps, 8 completions per prompt, 16 prompts per step, learning rate 2e-5, no KL penalty (beta 0), temperature 1.0, and at most 64 new tokens per completion.

Multi-turn games use `trainer/multiturn_grpo.py`, because TRL's GRPO trainer assumes one completion per prompt. It has the same objective as the TRL runs: a group-normalised episode reward times the log-probability of the model's own reply tokens. Each turn is a separate sample, so the environment's text never enters the loss. It runs on a single GPU with Hugging Face generation.

`trainer.rollout` and `trainer.viz` replay the base, hardened and hacked policies on the same held-out tasks and build a side-by-side transcript page.

## Measured results (Qwen2.5-0.5B-Instruct)

**Base success rates** (temperature 1.0):

| Game | Strict | Loose |
| --- | --- | --- |
| `arith_compute` | 24% | 68% |
| `trading_sim` | 11% | — |
| `scrabble_lite` | 4% | — |
| `lights_out` | 3% | — |
| `snake` | 2% | — |
| `arith_target`, `clue_guess`, `clue_guess_easy`, `anagrams`, `word_hunt` | 0% | — |

The games near 0% give the model no reward signal to learn from as they stand.

**`number_hunt_easy`**, a multi-turn hidden-number game, on one RTX A5000 at learning rate 5e-6. Its base rate is 0% strict and 18% loose.
- **Hardened reward:** strict held-out accuracy went from 0% to 90% in 60 steps (10.5 minutes, about 10 s per step). Episodes shrank from 7.0 to 4.8 turns as the model learned to use the hints.
- **Hackable reward:** its own reward went from 19% to 100% while strict accuracy stayed at 0%. Replies grew from 2.6 to 10.3 words, because it learned to list about ten guesses per turn.
- **Replay on 24 held-out games:** the base model scores 0% (29% on the hackable reward), the hardened policy 83%, and the hacked policy 0% (100% on the hackable reward).

**`hot_and_cold`**, a multi-turn game compiled by Claude Haiku: base rate 1% strict, 11% loose.

## Limitations

- Held-out accuracy uses greedy generation, while the training reward is sampled at temperature 1.0. Compare trends, not absolute values.
- Multi-turn training runs on one GPU with Hugging Face generation, without vLLM.
- Run artifacts (checkpoints and metrics) are kept on the GPU server, not in this repository.

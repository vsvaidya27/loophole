# Trainer TODO (continue on the GPU box)

State: probe and GRPO script work on a Mac (HF generation, 2-step smoke run). Nothing has
run with vLLM or on a GPU yet, and no run has shown accuracy climbing.

## 1. Get the GPU box working (own GPU server, not Runpod)
- [ ] Check with Varun for TRL + vLLM versions that work for him; reuse them.
- [ ] `bash scripts/setup_gpu.sh`; fix version conflicts (vllm, torch, trl, transformers). Then pin
      the working versions in `requirements-trainer.txt`.
- [ ] Put `.env` on the box (only needed for the compiler; training itself needs no keys).

## 2. Verify the pipeline on GPU
- [ ] `python -m trainer.probe arith_compute --n 200 --temperature 1.0` (expect ~24% strict, ~68% loose)
- [ ] `python -m trainer.train arith_compute --vllm --out runs/smoke --steps 3 --eval-every 1`
- [ ] Confirm `--vllm` colocate works: check `vllm_gpu_memory_utilization` (0.3 is a guess) and
      that the held-out eval (HF `generate` on the same model) doesn't OOM or clash with vLLM.
- [ ] If eval clashes with vLLM, move the eval to vLLM or to a separate pass between steps.

## 3. Hit the "done when": toy game from <20% to >80% in <5 min
- [ ] Tune on `arith_compute` strict: lr (2e-5 default), `--prompts-per-step` (16), `--generations` (8),
      `--steps` (60), temperature (1.0), beta (0.0).
- [ ] Record wall-clock time to 80% held-out accuracy; log it in the README.
- [ ] Find 2-3 games that learn in <5 min (plan, Phase 2). `arith_target`, `clue_guess` and
      `clue_guess_easy` are 0% for the base model, so they give no signal. Retune their difficulty
      (or have the compiler target 10-30%) and re-probe.

## 4. The hacked-vs-hardened comparison (never cut)
- [ ] `--loose` run on `arith_compute` -> `runs/hacked`: reward should climb while strict held-out
      accuracy stays flat (watch `mean_words` rise as it spams numbers).
- [ ] Strict run -> `runs/hardened`: reward and accuracy climb together.
- [ ] If loose-parser hacking is weak here, make `clue_guess_easy` learnable and use its candidate-spam
      loophole, or add a stronger loophole to `arith_compute` (e.g. accept any number in the output).
- [ ] Save both `metrics.jsonl` files as the recorded backup.

## 5. Integration
- [ ] Pipe compiler output in: `python -m trainer.train compiled/game_xxxx.py ...` (loader already supports it).
- [ ] Probe a compiled game before training; reject if strict rate is 0% or >50%.
- [ ] Pretrained checkpoint kept as the on-stage backup (`<out>/model`).
- [ ] Stream `metrics.jsonl` to the dashboard (Anirudh): agree on the format or an endpoint
      (SpacetimeDB is optional).
- [ ] Ask the compiler to hit the 10-30% difficulty (add to the codegen prompt, then probe).

## Known rough edges
- Eval uses plain HF generate with temperature 0, so train reward (sampled at 1.0) and held-out
  accuracy are measured differently; compare trends, not absolute values.
- `info_json` is a string column because TRL forwards extra columns to reward functions.
- Requirements are unpinned.

## New games (branch `games`) - base rates on Qwen2.5-0.5B-Instruct, T=1.0, mean reward
anagrams 0%, word_hunt 0%, scrabble_lite 4%, snake 2%, lights_out 3%, trading_sim 11%.
Only `trading_sim` and `arith_compute` (24%) are near the 10-30% target. Options: a bigger
model (Qwen 1.5B), a short SFT warm start on reference answers, or easier tiers
(smaller grids, 5-letter racks, 1-2 foods). Re-probe on the GPU box before picking.

## Multi-turn (branch `multi-turn`)
- [x] Rollout loop + GRPO update: `trainer/multiturn_grpo.py`, dispatched from `trainer.train` for
      multi-turn games.
- [x] GPU box (RTX A5000, one GPU, lr 5e-6, defaults otherwise): probe `number_hunt_easy` 0% strict /
      18% loose (n=100, T=1.0), yet it learns. Hardened: strict held-out 0% -> 90% in 60 steps (10.5 min,
      about 10 s/step), turns per episode 7.0 -> 4.8 (it uses the hints). Hacked (--loose): loose 19% ->
      100%, strict stays 0%, words per reply 2.6 -> 10.3 (lists ~10 guesses per turn). No OOM at the
      default micro-batch.
- [x] Compiled multi-turn game (`hot_and_cold`, compiled by Haiku): probe 1% strict / 11% loose; see the
      runs for its curves.
- [ ] Single GPU only (no accelerate / multi-GPU split yet) and HF `generate` (no vLLM).
- [x] Rollout/replay page: `trainer.rollout` dispatches on `kind`; each policy plays the same held-out
      seeds in the fixed and the hackable game, and `trainer.viz` shows both transcripts.
      number_hunt_easy, 24 held-out games: base 0% / hackable 29%, hardened 83%, hacked 0% / hackable 100%.

# Trainer TODO (continue on the GPU box)

State: probe and GRPO script work on a Mac (HF generation, 2-step smoke run). Nothing has
run with vLLM or on a GPU yet, and no run has shown accuracy climbing.

## 1. Get the GPU box working
- [ ] Check with Varun: does he already have a working Runpod pod / TRL + vLLM versions? Reuse his.
- [ ] `bash scripts/setup_runpod.sh`; fix version conflicts (vllm, torch, trl, transformers). Then pin
      the working versions in `requirements-trainer.txt`.
- [ ] Put `.env` on the box (only needed for the compiler; training itself needs no keys).
- [ ] Fallback if Runpod stalls: Modal wrapper (`trainer/modal_app.py`) that runs the same
      `python -m trainer.train` command on a GPU and writes `metrics.jsonl` to a Volume.
      Note the Runpod prize needs the demo and recorded runs to be on Runpod.

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

# loophole

Cal Hacks 2026: one engine that compiles, hardens and trains RL environments. We prove
it on Prime Intellect Environments Hub environments first, then point it at a game a
judge types live. The full plan, demo script and timeline are in
[docs/BUILD_PLAN.pdf](docs/BUILD_PLAN.pdf).

## Components

| Component | What it does | Owner |
| --- | --- | --- |
| Hardening engine | Hacker / judge / fixer / solver loop on a reward function (Claude for each role); runs the hub audit that produces the leaderboard | Varun |
| Invariant store | Turns each confirmed exploit into a reusable rule in `invariants.db` (mechanism, preconditions, defense) | Varun |
| Invariant graph | Graph view of the stored rules and how they connect (NetworkX) | Rishab |
| Env compiler | Plain-English game → single-turn verifiers environment (task generator, parser, reward, reference solver) | Rohan |
| Trainer | GRPO on a 0.5–1B model (TRL + vLLM on Runpod); streams reward and held-out accuracy | Rohan |
| Dashboard | Leaderboard, invariant graph, game input box, live training curves | Anirudh |

All environments share Prime Intellect's [verifiers](https://github.com/PrimeIntellect-ai/verifiers)
interface, so hub environments and compiled games run through the same engine.

## Repo layout

```
docs/                          build plan
scripts/check_leaderboard.py   acceptance check for the hub audit (see below)
```

Suggested homes for new work, so branches don't collide: `trainer/`, `compiler/`,
`harden/` (hardening engine + invariant store), `dashboard/`. Audit outputs will land
in `results/`, `patches/<env_id>/` and `invariants.db`.

## Working on a branch

```bash
git clone git@github.com:vsvaidya27/loophole.git
cd loophole
git checkout -b <your-name>/<topic>
# ...work, commit...
git push -u origin <your-name>/<topic>
```

Open a PR into `main` when something works. Keep `main` demoable.

## Setup

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- Put API keys in a `.env` file at the repo root (`ANTHROPIC_API_KEY=...`). It is
  gitignored; never commit keys.
- Hub environments install with uv, e.g.
  `uv pip install reverse-text --extra-index-url https://hub.primeintellect.ai/primeintellect/simple/`.
  Use verifiers 0.3.x: it runs both the classic and the v1 environment APIs (0.4 drops
  the classic one, which most hub environments still use).

## Leaderboard checker

`scripts/check_leaderboard.py` exits 0 only when the hub audit results are complete and
reproducible. It re-scores every logged exploit against the original and patched
reward functions itself instead of trusting numbers in the results. Its docstring
documents the evidence files the audit must write. It is still a draft under review;
once approved it will not change.

```bash
python scripts/check_leaderboard.py
```

## Env compiler (phase 1)

`env_compiler/` holds the fixed environment template (`template.py`), the validation
gates (`validate.py`), two hand-written game specs (`games/arith_target.py`,
`games/clue_guess.py`) and a verifiers adapter (`verifiers_env.py`). Each game has a
strict parser and a loose one (`strict=False`) for the recorded hacked run.

```bash
python -m env_compiler   # run the gates on every game
pytest tests/
```

# loophole

Cal Hacks 2026: one engine that compiles, hardens and trains RL environments. We prove
it on Prime Intellect Environments Hub environments first, then point it at a game a
judge types live. The full plan, demo script and timeline are in
[docs/BUILD_PLAN.pdf](docs/BUILD_PLAN.pdf).

> **Plan amendment: multi-turn.** The original plan assumed every environment is single-turn.
> That is still the default and the demo-critical path, but we are adding an opt-in multi-turn
> track (the environment answers each reply), selected by a `kind` field. The amended scope,
> per-component work, owners, phases and risks are in
> [docs/MULTITURN_PLAN.md](docs/MULTITURN_PLAN.md); where it differs from the PDF, the markdown
> plan wins for multi-turn work. It changes nothing for single-turn code.

## Live compiler / hacker / fixer / graph demo

See [the live pilot runbook](docs/LIVE_PILOT.md) for setup, key configuration,
service commands, completed Haiku pilot evidence, costs, and current limitations.
The dashboard shows the entire hosted knowledge graph, including clearly labeled
scripted calibration records. The completed generated-game pilot is single-turn;
it does not claim Hub leaderboard acceptance or trained-policy performance.

## Components

| Component | What it does | Owner |
| --- | --- | --- |
| Hardening engine | Hacker / judge / fixer / solver loop on a reward function (Claude for each role); runs the hub audit that produces the leaderboard | Varun |
| Invariant store | Turns each confirmed exploit into a reusable rule in `invariants.db` (mechanism, preconditions, defense); SpacetimeDB module and pusher by Rishab, audit-side writes and retrieval by Varun | Varun, Rishab |
| Invariant graph | Similarity edges and rules computed by SpacetimeDB reducers, plus `buildGraph` for the dashboard (see [docs/INVARIANT_STORE.md](docs/INVARIANT_STORE.md)) | Rishab |
| Env compiler | Plain-English game → single-turn verifiers environment (task generator, parser, reward, reference solver); or a multi-turn one when the game needs the environment to answer each reply ([plan](docs/MULTITURN_PLAN.md)) | Rohan |
| Trainer | GRPO on a 0.5–1B model (TRL + vLLM on our GPU server); streams reward and held-out accuracy; multi-turn games use a separate rollout loop (`trainer/multiturn_grpo.py`) | Rohan |
| Dashboard | Leaderboard, invariant graph, game input box, live training curves | Anirudh |

All environments share Prime Intellect's [verifiers](https://github.com/PrimeIntellect-ai/verifiers)
interface, so hub environments and compiled games run through the same engine.

Required Moss retrieval is in `harden/store/moss_retrieval.py` (see
[setup and credential instructions](docs/MOSS_RETRIEVAL.md)). Graph contracts and hacker/fixer adapters are in `harden/store/retrieval.py`
and `harden/store/knowledge_loop.py`. See [the integration guide](docs/GRAPH_RETRIEVAL.md)
for the plan, orchestration example, and cross-branch tests.

## Repo layout

```
docs/                          build plan, multi-turn plan, invariant store plan
scripts/check_leaderboard.py   acceptance check for the hub audit (see below)
spacetimedb/                   SpacetimeDB module for the invariant store (cd spacetimedb && npm install && npm test)
fixtures/                      seed invariants with MiniLM embeddings, for graph and dashboard work
harden/store/                  Python side of the invariant store (exploit class taxonomy so far)
spacetime.json                 SpacetimeDB CLI config (database "loophole", local server)
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

`python -m env_compiler.compile "<description>"` compiles a new game with Claude Haiku 5.5
(`ANTHROPIC_API_KEY` in `.env`). `ENV_COMPILER_MODEL` picks another Claude model (for example
`claude-opus-5-5`), `ENV_COMPILER_EFFORT` sets its effort (default `medium`), and
`--provider gemini` or `ENV_COMPILER_PROVIDER=gemini` switches to Gemini (`GEMINI_API_KEY`).

Games (`env_compiler/games/`), each with a strict parser and a loose (hackable) one:

| Game | Type | Loose-parser exploit |
| --- | --- | --- |
| `arith_target`, `arith_compute`, `clue_guess`, `clue_guess_easy` | exact-match puzzles | any matching candidate anywhere in the output |
| `anagrams`, `word_hunt`, `scrabble_lite` | word games (bundled ENABLE list), partial credit | no cap on listed words, so spam words |
| `snake`, `lights_out` | simulators (`frames` replays the plan) | spam many move strings, best one counts |
| `trading_sim` | simulated market with planted momentum (not real data) | hedge BUY and SELL, or use an oversized position |

## Trainer (phase 1)

`trainer/` runs GRPO (TRL) on any game and writes `metrics.jsonl` for the dashboard:
training reward plus held-out accuracy (always scored with the strict parser, so a
run against the loose parser shows reward climbing while true accuracy stays flat).

```bash
python -m trainer.probe arith_compute --n 100 --temperature 1.0   # base-model success rate
python -m trainer.train arith_compute --out runs/hardened          # strict parser
python -m trainer.train arith_compute --loose --out runs/hacked    # hackable parser
```

Add `--vllm` on the GPU box (`scripts/setup_gpu.sh` installs everything). Without it
generation uses plain HF, which is fine for a smoke test on a laptop.

Measured on Qwen2.5-0.5B-Instruct at temperature 1.0: `arith_compute` 24% strict / 68%
loose; `arith_target`, `clue_guess` and `clue_guess_easy` 0%, too hard to learn from as
they stand, so use `arith_compute` for the demo until those are retuned.

## Voice-agent environments (`voice_env/`)

A support-agent scenario (an electronics store refund desk with a written policy and a
secret discount code). The policy decides the correct action from the order facts, so we know
the ground truth of every call.

- **Option 1, judge hardening (offline):** the reward is an LLM-judge metric over call
  transcripts (the same `{name, prompt}` shape as a Cartesia custom metric). A hacker writes
  agent behaviours meant to fool the judge while breaking policy, Gemini simulates the calls,
  and a fixer rewrites the judge prompt. Reports attack success rate and benign pass rate.
  ```bash
  python -m voice_env.harden --rounds 3 --out results/voice_audit
  ```
- **Option 2, live calls:** `voice_env/live_call.py` drives a real Cartesia agent over its
  WebSocket with a simulated customer (Gemini writes the lines, Cartesia Sonic speaks them).
  The transcript comes back as text events and the call is scored by the agent's assigned
  Cartesia metrics plus our ground truth.
  ```bash
  python -m voice_env.live_call --agent AGENT_ID --turns 3
  ```
- `voice_env/cartesia.py` is a small client for agents, metrics (create, assign, results) and
  calls. Cartesia metrics have no update endpoint, so a hardened judge prompt is published as
  a new, versioned metric. Needs `CARTESIA_API_KEY` and `GEMINI_API_KEY` in `.env`.
- The simulation side (customer, agent under test, judge, call classifier) runs on Claude Haiku 5.5 at low effort, and so do the hacker and fixer (the Gemini free tier allows only 20 requests a day). `VOICE_ENV_SIM=gemini` / `VOICE_ENV_PLANNER=gemini` switch them back. Gemini calls are throttled (`VOICE_ENV_MIN_INTERVAL`, default 2s); all calls are cached in `.cache/`. Needs `ANTHROPIC_API_KEY` too.

## Multi-turn track (experimental, `multi-turn` branch)

A separate environment type for games where the environment answers each reply. It sits next
to the single-turn `GameEnv` and is selected by `kind == "multi"`; nothing in the single-turn
path (games, trainer, hardening, leaderboard checker) depends on it.

- `env_compiler/multiturn.py`: `MultiTurnGameEnv` with `reset(rng)`, `step(state, reply)`,
  an episode-level `reward(state)`, a scripted `reference_policy` and a `random_policy`.
  `play(policy, seed)` runs a full episode. State is JSON-serialisable.
- Games (`MULTI_GAMES`, kept apart from `GAMES`): `number_hunt` (higher/lower) and
  `live_mastermind` (the interactive version of `clue_guess`). Loose parser: a reply that lists
  many guesses counts every one, so spamming wins.
- Gates: `validate()` dispatches on `kind`. Multi-turn requires a reference policy that wins
  every episode, near-zero null and random policies, deterministic resets, and episodes that
  end within `max_turns`.
- Compiler: the fit check returns `single`, `multi` or `reject` and routes the game. Multi-turn games
  use their own template and worked example; `--single-only` refuses them.
- verifiers: `load_environment("number_hunt")` returns a `MultiTurnEnv` adapter (`GameMultiTurnEnv`).
- Trainer: `python -m trainer.train number_hunt_easy --out runs/x` runs a small self-contained GRPO
  loop (`trainer/multiturn_grpo.py`) instead of TRL, because TRL's `GRPOTrainer` assumes one
  completion per prompt (and the pinned TRL 0.24 has no multi-turn hook). Same objective as our TRL
  runs (beta 0, one update per batch): group-normalised episode reward times the log-probability of
  the model's own reply tokens, with each turn a separate (context, reply) sample so environment text
  never enters the loss. Metrics land in the same `metrics.jsonl` format (held-out accuracy is strict
  and greedy). Single GPU, HF generation, no vLLM. `trainer.probe` reports a game's base solve rate.
- Hardening: `python -m harden.game_audit GAME` runs the audit loop on single- and multi-turn games
  (Claude probes the shipped game, exact replay verifies, the fixer writes a `tighten` rule) and
  writes `hardened/<name>.py`; train on it with `--oracle GAME`. `python scripts/pipeline.py
  "description"` runs compile, harden, train (hardened and hacked) and the replay page in one go.
- Not supported yet: multi-turn entries in the leaderboard evidence schema (`check_leaderboard.py`
  scores one string per completion; any change there goes through Varun).

## Live demo dashboard and pilot status

Run `npm ci --prefix dashboard` then `npm run dev --prefix dashboard` to view the live
knowledge graph at `http://127.0.0.1:5173/`. It subscribes to the hosted database directly.
See [live demo status](docs/LIVE_DEMO_STATUS.md) for measured compiler calibration
results, the prepared Prime Intellect pilot, and the unfinished audit-runner work.

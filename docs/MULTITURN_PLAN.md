# Multi-turn compatibility plan

Amends [BUILD_PLAN.pdf](BUILD_PLAN.pdf). Status: draft for team review.

> **Where the code is.** The multi-turn code described here is on branch
> [`multi-turn`](https://github.com/vsvaidya27/loophole/tree/multi-turn) and is **not merged into
> `main` yet**. File paths below (for example `env_compiler/multiturn.py`,
> `trainer/multiturn_grpo.py`) refer to that branch. This document was published to `main` first so
> the whole team plans against the same scope; when the branch merges, this file gets updated to
> match what landed.

## 1. What changed and why

The original plan assumed every environment is **single-turn**: one prompt, one reply of 64 tokens
or fewer, one reward. That assumption bought us three things: GRPO finishes in minutes, one answer
has one checkable reward, and compiled games share the `verifiers` single-turn type with hub
environments. The compiler's fit check refuses multi-turn games for the same reason.

We now want games where the environment answers each reply (a hidden-number game with
higher/lower feedback, Wordle, Mastermind, a scripted opponent, a support call). They are more
watchable in a demo and closer to how agents are really trained, and they have richer exploits
(stalling, spamming guesses inside one reply, leaking state through feedback).

**Decision:** multi-turn is an **additive track**, selected by a `kind` field (`"single"` or
`"multi"`). Single-turn stays the default and the demo-critical path. Nothing single-turn is
rewritten, and every shared entry point dispatches on `kind`.

### Principles
1. **`kind` is the only switch.** No component branches on anything else. `GameEnv.kind = "single"`,
   `MultiTurnGameEnv.kind = "multi"`.
2. **Single-turn behaviour and tests do not change.** `GAMES` holds single-turn games only; multi-turn
   games live in `MULTI_GAMES`, so code that iterates `GAMES` is unaffected.
3. **The reward is episode-level.** One scalar in [0, 1] per episode, computed from final state.
   Anything that wants per-turn credit shapes it inside `reward(state)`.
4. **Multi-turn must not block the single-turn demo.** The plan's "never cut" list (compiler,
   hardening loop, recorded hacked-versus-hardened comparison) stays on the single-turn path until
   the multi-turn path has passed the same checks.

### Non-goals (unchanged from the original plan)
Visual or audio-in games, real-time or live-data games, LLM-judge rewards inside the *game*
reward, more than about 10 turns per episode, replies longer than 64 tokens.

## 2. What is built (on branch `multi-turn`)

| Piece | State |
| --- | --- |
| `env_compiler/multiturn.py`: `MultiTurnGameEnv` (`reset`, `step`, `reward`, `reference_policy`, `random_policy`, `play`) | done, tested |
| Games: `number_hunt`, `number_hunt_easy`, `live_mastermind` (strict and loose parser each) | done, tested |
| Episode gates in `validate()` (reference wins every episode, null and random near 0, deterministic reset, ends within `max_turns`) | done, tested |
| Compiler fit check returns `single` / `multi` / `reject` and routes each game (multi on by default; `--single-only` refuses it) | done; real-model corpus 9/10 multi-turn compiles (see 8) |
| verifiers adapter `GameMultiTurnEnv` (`load_environment("number_hunt")`) | done; one episode driven by hand |
| Trainer: `trainer/multiturn_grpo.py` (own GRPO loop), dispatched by `trainer.train`; `trainer.probe` for solve rates | done; GPU run: hardened `number_hunt_easy` 0% -> 90% strict, hacked 100% loose / 0% strict |
| Replay page: `trainer.rollout` + `trainer.viz` render fixed and hackable transcripts per policy | done |
| Hardening engine, evidence schema, leaderboard checker, invariant store taxonomy, dashboard | **not started** (sections 4.5 to 4.8) |

## 3. Compatibility matrix

| Component | Owner | Single-turn today | Multi-turn work | Done when |
| --- | --- | --- | --- | --- |
| Env template and gates | Rohan | `GameEnv`, `validate_single` | built | gates pass for every game in `MULTI_GAMES` in CI |
| Env compiler | Rohan | fit check, codegen, gate loop (on Gemini) | live codegen test, test corpus, latency | 8 of 10 varied multi-turn descriptions compile and pass gates within 3 attempts |
| verifiers adapter | Rohan | `SingleTurnEnv` | built | a real rollout (not a hand-driven one) completes through `GameMultiTurnEnv` |
| Trainer | Rohan | TRL GRPO, vLLM, multi-GPU, LoRA, few-shot | GPU run, tuning, parity with the single-turn flags | hardened `number_hunt_easy` climbs; loose run diverges |
| Hardening engine (hacker, fixer, replay) | Varun | single completion, one reward function | transcript replay and episode scoring | a planted multi-turn exploit is found, patched, and replays low |
| Evidence schema and `check_leaderboard.py` | Varun | `completion` is a string | `kind` field and episode replay | checker passes on a mixed single/multi fixture |
| Invariant store and graph | Rishab | taxonomy of single-reply exploit classes | multi-turn classes, `kind` on rows | a rule from one multi-turn game retrieves on another |
| Dashboard | Anirudh | scores and curves | transcript and per-turn replay view | a multi-turn replay renders next to the single-turn ones |
| Voice environment | Rohan | transcript-judge audit (already conversation-shaped) | optionally express as a `MultiTurnGameEnv` | not required for the plan; see 4.9 |

## 4. Design by component

### 4.1 Template and gates (done)
`reset(rng) -> (state, first_message)`, `step(state, reply) -> (message, done)`, `reward(state)`.
State is JSON-serialisable because verifiers stores it in rollout state and the evidence files must
replay it. Strict mode reads one `<answer>` per reply; loose mode (`candidates`) reads every
candidate in the reply, which is the planted exploit for the recorded hacked run. `play(policy, seed)`
gives the policy its own random stream (it must not share the reset seed; a bug where it did made a
random policy win every episode).

### 4.2 Compiler
- The fit check classifies a description as `single`, `multi` or `reject`; older `{"fits": bool}`
  replies are still read as single/reject.
- Multi-turn codegen uses its own prompt, template (`multiturn.py`) and worked example
  (`multiturn_games.py`). Gates are the episode gates above.
- **Open work:** run it against a real model (the only multi-turn compile test so far uses a fake
  client); build a corpus of about 10 descriptions (hint games, Wordle-like, scripted opponent,
  twenty questions, code-breaking); measure latency against the 30-second target; move the compiler
  off Gemini (free tier exhausted; the Anthropic-prize pitch says Claude runs the compiler).
- **Risk:** generated multi-turn code is harder (a correct `step` and a reference policy that wins
  100% of episodes). Mitigation: keep the allow flag off for the live demo path unless the corpus
  passes, and keep a hand-written fallback game ready.

### 4.3 verifiers adapter
`GameMultiTurnEnv(vf.MultiTurnEnv)`: `setup_state` resets the game from `info["seed"]`,
`env_response` calls `step`, and a finished game sets `final_env_response`. The reward function reads
`state["game_state"]`. Dataset rows carry only the seed and the first message. **Open work:** drive a
real model through a full `rollout` (so far only `setup_state` and `env_response` were called by hand).

### 4.4 Trainer
- **Why not TRL:** `GRPOTrainer` assumes one completion per prompt, and the TRL 0.24 pinned for the
  GPU box has no multi-turn hook. Newer TRL has `environment_factory`, but it needs
  transformers 5.2 or newer, which conflicts with the pinned vllm 0.11.0 / transformers 4.57.1.
  Revisit if we ever unpin.
- **What exists:** `multiturn_grpo.py`. Episodes run in lock step with batched HF `generate`. Each
  model turn is a separate (context, reply) sample, so environment text never enters the loss.
  Objective: group-normalised episode reward times the log-probability of the model's own tokens
  (beta 0, one update per batch), the same as our single-turn TRL runs. Metrics use the same
  `metrics.jsonl` keys (`heldout_acc` strict and greedy, plus `mean_turns`).
- **Gaps against the single-turn trainer:** single GPU only, HF generation (no vLLM), and it ignores
  `--shots` and `--lora`. The update is memory-heavy (full logits per micro-batch); one step took
  about 450 s on a Mac. Real GPU numbers are unknown.
- **Parity work, in order:** (1) run on the GPU box and tune lr and batch (a first tiny update at
  lr 1e-5 destabilised the policy); (2) honour `--shots` (put solved episodes in the first message)
  and `--lora`; (3) compute logits only at reply positions to cut memory; (4) vLLM generation and
  multi-GPU only if training time demands it.
- **Done when:** `number_hunt_easy` hardened accuracy rises on the GPU box and the `--loose` run shows
  loose accuracy rising while strict stays flat.

### 4.5 Hardening engine: replay semantics
The leaderboard contract scores one completion under the original and the patched reward function
("PASS under R", "LOW under R"). For an episode the natural equivalent is **replaying the agent's
logged replies against the environment**:

1. An attempt is `(seed, replies[])`. The environment is rebuilt from the seed (`reset`).
2. Replay feeds the logged replies to `step` in order, with no model in the loop, and stops when the
   game ends or the replies run out. Reward is `reward(state)`.
3. Original environment: the exploit replies should win (PASS). Patched environment: the same replies
   should lose (LOW), and the reference policy must still win on the patched environment.
4. Because the environment's messages come from the game and not the log, replays are deterministic
   and need no API calls, exactly like the single-turn replays.

A subtlety: if a patch changes the feedback the environment gives, a replayed reply sequence is no
longer a conversation the model would have had. That is acceptable for checking that the *exploit
sequence* stops paying, and it should be stated in the evidence notes.

Hacker and fixer work on the same objects as before, with the hacker producing reply sequences
(or a policy) and the fixer patching `step`, `candidates` or `reward`. Planted multi-turn exploit
for the demo: the loose parser (many guesses in one reply). Cap the loop at 5 iterations as before.

### 4.6 Evidence schema and `check_leaderboard.py` (Varun's file; do not edit without him)
Proposed additive change, so existing single-turn entries are untouched:
- `runtime.json` gains `"kind": "single" | "multi"` (default single).
- Multi-turn records keep `example_index` (an index into the seeded episode list), `example_digest`
  (digest of the reset state and first message), and replace the string `completion` with a list of
  reply strings; `reference_completion` becomes the reference policy's reply list.
- Scoring for `kind: multi` uses the replay in 4.5; `R_ref`, PASS (>= 0.8 x ref) and LOW (<= 0.5 x ref)
  keep their meaning with episode rewards. `ENTRY_FIELDS` and the leaderboard columns do not change.

This needs Varun's review before any change; until then multi-turn games are not eligible for the
checked leaderboard (the hub audit is single-turn anyway).

### 4.7 Invariant store and graph (Rishab)
Schema is unchanged (`mechanism`, `root_cause`, `preconditions`, `defense_pattern`). Add `kind` to rows
and these exploit classes: **multi-candidate-in-reply** (spam many answers in one turn),
**turn-burning / stalling** (no progress while the clock runs), **feedback leakage** (state recoverable
from environment messages), **opponent exploitation** (a scripted opponent has a fixed weakness), and
**premature termination** (ending an episode early to lock in reward). Retrieval for a new multi-turn
game should key on those classes.

### 4.8 Dashboard (Anirudh)
Transcript view with agent and environment turns, per-turn replay using the game's `frames` hook
(optional on `MultiTurnGameEnv`; not implemented for the example games yet), and one extra training
metric (`mean_turns`). The existing single-turn replay page (`trainer/viz.py`) is unchanged.

### 4.9 Voice environment
The refund-desk judge audit already works on conversation transcripts, but it is a different shape
(the *judge* is the reward, and the policy is an agent prompt). Folding it into `MultiTurnGameEnv` is
optional and not on the critical path; do it only if the hardening engine needs one interface for both.

## 5. Phases

| Phase | Work | Done when |
| --- | --- | --- |
| M0 (done, on branch `multi-turn`) | Template, games, gates, compiler fit check, adapter, trainer loop, tests | full suite passes on the branch (123 tests) |
| M0b | Merge `multi-turn` into `main` (after M1 shows the trainer learns) | single-turn tests still green; this file updated to match |
| M1 GPU validation (done for `number_hunt_easy`) | Probe and train `number_hunt_easy` and `live_mastermind`; tune lr and batch; fix memory | hardened climbs, loose diverges, curves saved |
| M2 trainer parity | `--shots`, `--lora`, logits-at-reply-positions, optional vLLM | same flags as single-turn work or error clearly |
| M3 compiler | Real-model corpus run, latency, Claude backend | corpus target in section 3 met |
| M4 hardening | Replay, planted exploit found and patched, evidence note | needs Varun: schema review first |
| M5 store and dashboard | New classes, `kind` on rows, transcript view | needs Rishab and Anirudh |
| M6 demo | One multi-turn game in the demo (Wordle-like or number line) with before/after policies | rehearsed twice |

M1 gates everything after it: nothing else is worth building if the multi-turn trainer cannot learn.

## 6. Risks

| Risk | Mitigation |
| --- | --- |
| Multi-turn training is slow or unstable on the GPU box | M1 first; keep the single-turn demo as the primary; recorded run as a backup |
| Generated multi-turn games are unreliable | Allow flag off by default; hand-written fallback games; corpus gate before demoing it |
| Changes leak into the single-turn path | `kind` dispatch only; full single-turn test suite runs on every change; no edits to `check_leaderboard.py` without Varun |
| Reward is sparse (win or lose) so GRPO gets no signal | Easier tiers (smaller range, fewer turns), few-shot first message, optional shaped partial credit inside `reward(state)` |
| Base model too weak (3% on `number_hunt_easy`) | Few-shot examples, a short supervised warm start (`trainer/sft.py` exists on `main`), or a larger model |
| Team attention split | Multi-turn is explicitly off the "never cut" list; cut it first if we fall behind |

## 7. Open questions
- Varun: is the evidence change in 4.6 acceptable, and should multi-turn games ever appear on the
  checked leaderboard, or only in the live-game beat?
- Rishab: do the new exploit classes in 4.7 fit the taxonomy file as-is?
- Anirudh: which transcript format is easiest to render?
- Team: pick the hero multi-turn demo game (hint game, Wordle-like, or something with a scripted opponent).

## 8. Decision log
- **2026-10-24 (evening):** multi-turn compiles by default; the fit check picks single or multi per
  game, and `--single-only` restores the old refusal. Reason: on Claude Haiku 5.5 a 15-description
  corpus routed 15/15 correctly (10 multi, 3 single, 2 reject) and 9/10 multi-turn games compiled
  and passed the episode gates within 3 attempts (15-50 s each), meeting the section 3 target.
- **2026-10-24 (later):** the plan was published to `main` ahead of the code, at the owner's request and
  without review, so the team shares one scope. The code stays on `multi-turn` until M0b.
- **2026-10-24:** single-turn stays the default and the demo path; multi-turn is an additive track
  behind `kind`. Reason: protects the demo-critical path while allowing richer games. Supersedes the
  original plan's "refuse multi-turn" rule only when `--allow-multiturn` is passed.

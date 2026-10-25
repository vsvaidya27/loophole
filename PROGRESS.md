# Leaderboard audit progress

Running log for the reward false-positive leaderboard (docs/BUILD_PLAN.pdf, beat 2).
Contract: `scripts/check_leaderboard.py` (frozen at `cd376a7`). API spend cap $40.

## 2026-10-24

**Spend so far: $0.1424** in `results/spend_ledger.jsonl`: $0.0493 of Claude smoke tests (`env_id` "smoke-test", see below) and $0.0931 testing the env compiler (`env_id` "compiler-test"). On Claude Opus 5.5 the test cost $0.0887 (5 calls); on Claude Haiku 5.5, now the default, $0.0044 (6 calls). Both refused a multi-turn game and compiled two new games that pass the gates.

Verified offline, through the checker's own worker in each env's venv:

- All 16 selected environments load, and the ground-truth reference for 10 rows spread
  across each dataset scores > 0 (full credit in every case). The `reference_check`
  notes in envs.yaml for deepscaler-math, reasoning-gym-env, temporal-bench, ascii-tree
  and countdown said 0/10 (or 0/0); they were out of date and are corrected.
- The tightened-grader wrapper templates in `harden/audit/patching.py` (legacy and v1)
  work in all 16: same examples and dataset size as the original, the gold answer reaches
  `tighten()`, and rewards change only where the rule says.
- Loading reasoning-core-env takes about 2 minutes per scoring run; the others take 5-30 s.

Harness (`harden/audit/`):

- Done: `llm.py` (spend ledger and per-call logging), `common.py`, `scoring.py`,
  `inspect_env.py` (now also shows each parser's extract function and reasoning-core's
  per-task scorers), `verify.py`, `roles.py`, `patching.py`.
- New: `leaderboard.py` builds `results/leaderboard.json` / `.md` from the evidence only
  (exploits from `replays/`, status and rates by re-scoring). On a copy of the earlier
  synthetic fixture (17 entries: patched, unpatched, robust, failed_to_run) it reproduces
  the fixture's leaderboard exactly, and the checker passes on the rebuilt tree.
- New: `invariants.py`, the extractor hook `harden.store.reconcile` calls for an exploit
  with no invariant row (it used to import it from `loop.py`).
- Done: the per-environment loop in `loop.py`; implementation and validation details below.
  No paid environment audit has been run, so there is no published audit evidence,
  leaderboard or invariants.db yet.

Evidence contract the loop has to write for `leaderboard.py` (beyond the checker docstring):
each `replays/<exploit_id>.json` carries `exploit_class`; an env that fails twice gets
`failed.json` `{"reason": ...}` in its evidence dir instead of `runtime.json`.

### Real-API smoke tests of the Claude integration ($0.048, 4 calls, all through `harden/audit/llm.py`)

1. Client: one structured-output call to claude-opus-5-5 at low effort returned the
   exact JSON asked for (stop `end_turn`, $0.0013).
2. Solver and verifier on 3 reverse-text tasks (examples 11, 222, 733): 3 of 3 answers
   parsed; the strict check marked all 3 correct and the real grader gave each 1.0 (the
   reference's score). The Claude judgment path agreed with the strict check on 3 of 3.
   The solver request was declined by claude-opus-5-5 after 73 output tokens and served
   by the server-side fallback (claude-opus-5); both attempts were billed and logged.
3. Invariant extraction from the fixture's synthetic exploit into a temporary mirror
   database: all text fields >= 10 characters, the sample is not quoted, and the row
   kept the exploit class it was given.
4. Accounting: `api_calls.jsonl` ($0.0480) equals the ledger's settled delta, and no
   reservation was left open.

Gap found: `llm.py` recorded `refusal_category` only when the final response was a
refusal. When the fallback answers, the declining hop's category is in a `fallback`
content block (`trigger.category`) that `llm.py` did not read, so the solver decline above
has no recorded reason. It also joined every text block, so text a declining model wrote
before the fallback block would have been mixed into the served answer.

Fixed: `llm.read_response()` logs each declining hop as `declined_hops` (model, fallback
model, trigger, `refusal_category`, "uncategorized" when unnamed) in `api_calls.jsonl` and
the ledger, and takes the answer only from the text after the last fallback block.
Checked offline with SDK-built responses (no fallback, one hop with partial text before
it, an unnamed category, two hops, a final refusal), through `read_response` and the full
`Claude.call` path with a stubbed client and a temporary ledger: 12 of 12 pass. Smoke test
1 re-run against the real API passes and logs `declined_hops: []` ($0.0013).
**Spend now $0.0493.**

### Per-environment audit loop completed

`harden/audit/loop.py` now implements the complete command-line audit:

- Samples 24 spread ground-truth examples and a separate solver pool, checks positive
  reference rewards, and collects distinct independently verified model completions.
- Uses cached strict verdicts first; inconclusive responses require a Claude verdict.
  Missing or refused judgments are retried once and never counted as incorrect attacks.
- Probes, scores, verifies and repairs for at most five iterations. Repairs must pass
  static checks, close every confirmed exploit, retain every reference, preserve at
  least 90% of benign answers and passing model answers, and have five model records.
  Accepted patches are re-probed before an early successful stop.
- Writes attempts, benign records, replay cases with exploit classes, chained patch
  digests, runtime metadata, per-run summaries and invariant rows. The leaderboard
  builder re-scores the evidence to derive the final status. Raw proposals, solver
  responses and repair rejection reasons are retained separately for diagnosis.
- Retries failed operations at most twice, honors the existing global and per-run
  spend caps, and writes `failed.json` without `runtime.json` for incomplete runs.
  A budget stop after completed iterations can retain an honest `unpatched` result.
  Missing invariant extractions are listed in `summary.json` and return exit code 1;
  `harden.store.reconcile` can fill them in later. Reruns archive the previous evidence
  and its accepted patch together and keep the install log.

Validation in `tests/test_audit_loop.py`: 20 offline tests pass, plus one opt-in test
against the installed reverse-text environment. The integration test uses the real
inspection/scoring workers and frozen checker, with controlled model-role responses;
its repaired result passes replay, patch-chain, benign and invariant checks. It runs
in a temporary directory and is not leaderboard evidence. **API spend for this work: $0.**

```bash
# Offline orchestration and checker-contract tests (no pytest dependency):
.venvs/hub/bin/python -m unittest discover -s tests -p test_audit_loop.py -v

# Installed reverse-text integration, using its cached dataset and no API calls:
AUDIT_REAL_ENV_TEST=1 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
  .venvs/hub/bin/python -m unittest discover -s tests -p test_audit_loop.py -k installed_environment -v

# Start the first real audit with a $2 per-run cap:
.venvs/hub/bin/python -m harden.audit.loop primeintellect/reverse-text --cap 2
```

## Next steps

1. **Run the environments**: a real-API smoke test on one cheap env with a $2 sub-cap
   first, check its evidence with the checker, then the remaining envs, committing each
   one as it finishes and logging its cost here.
2. `leaderboard.py`, then `python -m harden.store.reconcile`, then `leaderboard.py` again
   (reconcile can add calls), then `python3 scripts/check_leaderboard.py` until it exits 0.
3. RUN_NOTES.md, then push (`cd376a7`, `0721541` and the commits after them are local only).

# Leaderboard audit progress

Running log for the reward false-positive leaderboard (docs/BUILD_PLAN.pdf, beat 2).
Contract: `scripts/check_leaderboard.py` (frozen at `cd376a7`). API spend cap $40.

## 2026-10-24

**Spend so far: $0.00** (no Anthropic API calls made yet; `results/spend_ledger.jsonl` does not exist).

Verified offline, through the checker's own worker in each env's venv:

- All 16 selected environments load, and the ground-truth reference for 10 rows spread
  across each dataset scores > 0 (full credit in every case). The `reference_check`
  notes in envs.yaml for deepscaler-math, reasoning-gym-env, temporal-bench, ascii-tree
  and countdown said 0/10 (or 0/0); they were out of date and are corrected.
- The tightened-grader wrapper templates in `harden/audit/patching.py` (legacy and v1)
  work in all 16: same examples and dataset size as the original, the gold answer reaches
  `tighten()`, and rewards change only where the rule says.
- Loading reasoning-core-env takes about 2 minutes per scoring run; the others take 5-30 s.

Harness (`harden/audit/`, uncommitted):

- Done: `llm.py` (spend ledger and per-call logging), `common.py`, `scoring.py`,
  `inspect_env.py` (now also shows each parser's extract function and reasoning-core's
  per-task scorers), `verify.py`, `roles.py`, `patching.py`.
- New: `leaderboard.py` builds `results/leaderboard.json` / `.md` from the evidence only
  (exploits from `replays/`, status and rates by re-scoring). On a copy of the earlier
  synthetic fixture (17 entries: patched, unpatched, robust, failed_to_run) it reproduces
  the fixture's leaderboard exactly, and the checker passes on the rebuilt tree.
- New: `invariants.py`, the extractor hook `harden.store.reconcile` calls for an exploit
  with no invariant row (it used to import it from `loop.py`).
- Not done: the per-environment loop in `loop.py` (it stops at line 130). No environment
  has been run, so there is no evidence, leaderboard or invariants.db yet.

Evidence contract the loop has to write for `leaderboard.py` (beyond the checker docstring):
each `replays/<exploit_id>.json` carries `exploit_class`; an env that fails twice gets
`failed.json` `{"reason": ...}` in its evidence dir instead of `runtime.json`.

## Next steps

1. **Write the per-environment audit loop in `harden/audit/loop.py`.** It is still
   unwritten: the file stops at `Audit.verify()` (docstring only) and has no entry point.
   It needs setup (ground-truth and solver benign records), the iteration loop (probe,
   score, verify, repair, up to 5 iterations), the evidence files, and the invariant rows.
2. **Run the environments**: a smoke test on one cheap env with a $2 sub-cap first, check
   its evidence with the checker, then the remaining envs, committing each one as it
   finishes and logging its cost here.
3. `leaderboard.py`, then `python -m harden.store.reconcile`, then `leaderboard.py` again
   (reconcile can add calls), then `python3 scripts/check_leaderboard.py` until it exits 0.
4. RUN_NOTES.md, then push (`cd376a7`, `0721541` and the commits after them are local only).

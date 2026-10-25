# Full audit run notes — 2026-10-24

Started from `main` at `8e01a8b` after `git pull --ff-only origin main` reported
already up to date. The current build plan is `docs/BUILD_PLAN.pdf` (the former
`BUILD_PLAN.md` is no longer present). All 16 selections in `envs.yaml` were attempted.

## Results

- Selected environments: **11 patched, 1 robust on tested probes, 3 unpatched, 1 failed to load**.
- The leaderboard also preserves the three earlier installation failures: **19 entries** total.
- **180 probe submissions**, **360 ground-truth baseline records**, and **94 independently
  verified model baseline records** across the 15 environments that loaded.
- **95 confirmed exploit records and 95 complete invariants**: **60 closed**, **35 open**.
- **11 accepted repair files** under `patches/<owner>/<env>/patch.py`.
- All patched entries have measured attack success rate **0** on the saved attempts.
  Their benign pass rates are **96.88–100%** and meet the separate model-retention gate.
- Frozen full checker: **PASS, 0 failures** (`results/audit_batch/check_leaderboard.log`).

| Selected environment | Status | Rounds | Exploit records | ASR before → after | Benign after | API cost |
|---|---|---:|---:|---|---:|---:|
| beauduffy/ai2-arc | patched | 5 | 6 | 0.6667 → 0.0000 | 1.0000 | $1.5522 |
| harleycooper/nanochatAquaRat | patched | 5 | 12 | 0.8667 → 0.0000 | 1.0000 | $1.2507 |
| metavind/mini-sudoku | patched | 3 | 2 | 0.4444 → 0.0000 | 1.0000 | $0.6390 |
| primeintellect/ascii-tree | patched | 4 | 7 | 0.6667 → 0.0000 | 1.0000 | $1.0093 |
| primeintellect/deepscaler-math | patched | 5 | 6 | 0.6000 → 0.0000 | 1.0000 | $3.0856 |
| primeintellect/math500 | patched | 5 | 5 | 0.5333 → 0.0000 | 1.0000 | $1.6887 |
| primeintellect/mmlu-pro | patched | 2 | 1 | 0.3333 → 0.0000 | 1.0000 | $0.3471 |
| primeintellect/reverse-text | patched | 3 | 2 | 0.6667 → 0.0000 | 1.0000 | $0.5466 |
| runes/temporal-bench | patched | 5 | 14 | 1.0000 → 0.0000 | 1.0000 | $1.4545 |
| will/gsm8k | patched | 2 | 1 | 0.1667 → 0.0000 | 0.9688 | $0.3877 |
| will/reasoning-gym-env | patched | 4 | 4 | 0.6667 → 0.0000 | 1.0000 | $0.7068 |
| maziyar/OpenMed_PubMedQA | unpatched | 5 | 14 | 1.0000 → 1.0000 | 1.0000 | $1.0726 |
| sami/countdown | unpatched | 4 | 8 | 1.0000 → 1.0000 | 1.0000 | $1.8144 |
| srthkdev/contract_nli_env | unpatched | 5 | 13 | 1.0000 → 1.0000 | 1.0000 | $0.7134 |
| dimamachine/rosalind-bio | robust | 3 | 0 | 0.0000 → 0.0000 | 1.0000 | $0.3268 |
| sileod/reasoning-core-env | failed_to_run | 0 | 0 | — → — | — | $0.0000 |

These are bounded sampled audits, not exhaustive checks of each dataset or proofs of
security. Each loaded environment uses 24 spread ground-truth examples, a distinct
solver pool of up to 24 examples, ten probe examples, and at most five rounds of three
proposals. A patch accepted before round five is re-probed; the frozen contract permits
a repair in round five without a sixth round. The `robust` label for Rosalind means no
confirmed false positive in this run's nine proposals, with enough distinct incorrect
attempts to satisfy the checker.

## Open outcomes

- **PubMedQA, Contract NLI, Countdown:** all three solver batches were declined in each
  environment. No model answers were fabricated or substituted. Without at least five
  verified model baseline records, repairs cannot be accepted. Their 35 confirmed
  exploit records remain open in both the mirror and export. PubMedQA and Contract NLI
  completed five rounds; Countdown stopped after four at its $2.30 per-environment cap.
  More probe rounds alone would not fix the missing solver baseline.
- **Reasoning-core:** the offline attempt could not load the streaming dataset. Two
  network-enabled inspection attempts then stalled before returning rows; their workers
  were stopped after roughly 16.5 and 8.2 minutes, respectively. Captured stderr includes
  remote Parquet read timeouts. `load_diagnostic.json`, `load_stack_second.txt`, and
  `failed.json` retain the evidence. No grader result or robustness claim is available.
- The three earlier failures are unchanged: AIME2025 has incompatible published loader
  APIs, MetaMathQA's wheel lacks its module, and Base64Bench's wheel lacks its datasets.
  Their install logs and leaderboard failure reasons are preserved.

## Spend and recovery

At sweep completion, settled ledger spend was **$16.755505** of the **$40** cap, with zero open
reservations. It includes **$0.142360** of prior smoke/compiler tests and **$0.017800**
from the discarded reverse-text attempt. The new sweep therefore cost **$16.613145**.
Active audit evidence totals **$16.595345**; rounded per-environment leaderboard values
sum to **$16.5954**. Embeddings and final validation used no paid model calls.

Temporal-bench and reverse-text started with $2 caps; batch runs used $2.30. DeepScaleR
reached its first cap after three rounds and resumed from paid evidence with a $3.50
cumulative cap, completing rounds four and five. No run exceeded five rounds, and the
shared ledger retained its $40 limit and $1 reservation margin.

Reverse-text's first declined solver batch was excluded from its recovery rather than
rewritten or resubmitted. The exclusion indices and archive path are in its
`solver_exclusions.json`. All discarded evidence and its spend remain under
`results/discarded/` and the shared ledger. `results/audit_batch/runs.json` records the
initial batch attempts; **the final leaderboard and per-environment summaries are the
authoritative outcomes**, including the standalone recoveries.

## Publication with current main

The handoff incorporates main through `f2ca0f8`, including the live pipeline/dashboard
and multi-turn work. Both spend histories are retained without duplicate rows:
**$17.37688380 shared total**, of which **$0.62137880** belongs to the separate
compiler/game pilots. The audit-only costs above remain the original run measurements.
The saved evidence uses the Opus configuration from `8e01a8b`; current main defaults
to Haiku and requires an explicit global cap. Set `AUDIT_CAP_USD=40` for future bounded
runs. No new model calls were made to publish or integrate this handoff.

The committed database is `results/audit_batch/invariants.db`; the root database stays
an ignored live outbox. Ingestion adds these audit IDs to the existing hosted graph;
its total row count can exceed the 95 invariants in this batch because other pilots
already have data there.

After integration, 62 tests passed and one optional integration test was skipped across
audit/export/service-client/retrieval/budget/pusher suites. The full frozen checker
again passed with zero failures. The committed snapshot loaded all 95 invariants through
`SQLiteKnowledgeSource`, and a test query returned five candidates. Publication check
logs are in `results/audit_batch/publication_tests.log` and `publication_checker.log`.

## Harness changes

- Empty solver batches are logged and excluded while distinct batches can supply the
  baseline. Missing model records still prevent repair acceptance.
- Regex `re.compile()` and ordinary import aliases pass the repair static check; Python
  code compilation remains disallowed. Checker thresholds were not changed.
- `--resume` continues a completed unpatched run with fewer than five rounds, preserving
  its baseline, paid history, cumulative cap, and patch chain.
- `harden.store.export` exports reconciled graph batches with exact replay paths and
  SHA-256 hashes of accepted repair files. `scripts/embed_invariants.py` fills missing
  embeddings locally with normalized, 384-dimensional `all-MiniLM-L6-v2` vectors.

Validation: 30 tests passed and one opt-in installed-environment test was skipped across
`test_audit_loop.py`, `test_graph_export.py`, and `test_service_client.py`. The real audit
outputs additionally passed the complete installed-environment checker. Reconciliation
made **zero changes**; no extra extraction calls were needed. SQLite integrity and all
95 embedding dimensions, finite values, and norms were checked. The checker file remains
byte-for-byte unchanged from `cd376a7` (Git blob
`512017a27c32f36a63069feeb94ae558f3234a82`).

## Graph ingestion handoff

- `results/audit_batch/invariants.db`: committed read-only snapshot, with 60 patched and
  35 confirmed/open exploits. The root `invariants.db` remains the ignored live outbox.
- `results/invariant_graph_batch.json`: **19 environments, 95 embedded invariants, 11
  repair-file hashes**. Includes the open findings as open records.
- `results/evidence/`: baselines, attempts, independent judgments, replay cases, model
  usage, repair decisions, patch history and runtime metadata.
- `patches/`: accepted repair source files; installed environment packages were unchanged.

The batch was exercised through the real service client with mocked HTTP only: 19
`record_environment`, 95 `record_exploit`, 95 `record_invariant`, 95 `graph_on_invariant`,
and 60 `mark_exploit_patched` calls. **No hosted graph writes were made** and no mirror
rows were marked pushed. The dedicated graph writer token is not configured here.

Rebuild/export commands, from this repository. On a fresh checkout, initialize the
ignored local mirror from the snapshot; the command preserves an existing outbox:

```sh
test -e invariants.db || cp results/audit_batch/invariants.db invariants.db
HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 .venvs/hub/bin/python -m harden.audit.leaderboard
.venvs/hub/bin/python -m harden.store.reconcile
# Rebuild the leaderboard again if reconciliation adds API calls.
HF_HUB_OFFLINE=1 uv run --offline --with sentence-transformers python scripts/embed_invariants.py
.venvs/hub/bin/python -m harden.store.export
HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 .venvs/hub/bin/python scripts/check_leaderboard.py --jobs 3
```

To ingest once the dedicated token has been installed privately, use the existing client
and the connection details in `deployment/README.md`:

```sh
export SPACETIME_HOST=https://maincloud.spacetimedb.com
export SPACETIME_DB=loophole-knowledge-calhacks-2026
export SPACETIME_TOKEN_FILE=/private/path/to/knowledge-writer-token
.venvs/hub/bin/python -m harden.store.service_client push results/invariant_graph_batch.json
```

The client triggers graph updates and supports retrying the same IDs. It does not upload
repair/evidence files or mark SQLite rows pushed; retain these repository artifacts
alongside the batch. The audit code, results, database, and accepted patches are
versioned together in this repository (the database as an immutable audit snapshot). See the frontend and graph RAG handoff in
`PROGRESS.md` for subscription types, invariant IDs, and retrieval entry points.
Hosted ingestion remains a separate step from publishing these Git artifacts.

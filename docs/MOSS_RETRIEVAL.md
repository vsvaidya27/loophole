# Required Moss retrieval

Moss is the retrieval engine for compiler audit pilots, multi-turn GameAudit, the
full Hub audit and bounded Hub pilot, the knowledge CLI, and cross-environment
transfer orchestration. There is no production keyword fallback. SpacetimeDB
remains authoritative for records and graph edges; `GraphRetriever` is retained
only as a deterministic baseline for comparisons and unit fixtures.

## Credentials and installation

The code is ready to configure. Put both values in the ignored repository `.env`:

```dotenv
MOSS_PROJECT_ID=your-project-id
MOSS_PROJECT_KEY=your-project-key
```

Get the project ID and project key from https://portal.usemoss.dev/. These are
Moss credentials, separate from the Anthropic key. Never use a `VITE_` prefix or
put the project key in frontend code, Git, or chat. Blank fields are in the local
`.env` and `config/pilot.env.example`.

The supported SDK is pinned to `moss==1.21.0` in `requirements-pipeline.txt` and
`requirements-trainer.txt`. The local hub runtime already has it installed.

```sh
uv pip install --python .venvs/hub/bin/python -r requirements-pipeline.txt
.venvs/hub/bin/python -m harden.live doctor
```

The doctor reports only whether credentials are configured; it does not print them
or authenticate with Moss. Missing credentials stop audits before paid compilation
or hacker/fixer calls. Services that only display or write existing records can
continue running without starting retrieval.

## Check retrieval without calling a language model

After saving both credentials:

```sh
.venvs/hub/bin/python -m harden.live retrieve \
  --target-env game/new-moss-demo \
  --query 'The grader extracts every guess and pays when any candidate matches. How should it reject ambiguous answers?' \
  --reward-source compiled/game_852c07fa.py
```

This reads the hosted store, initializes Moss, and prints selected IDs, relevance,
reasons, and a retrieval receipt. It makes no Anthropic completion or database
write. Moss may authenticate, download its embedding model, and report usage; no
Moss price or latency guarantee is made by this integration.

Run the usual pipeline afterward. Both kinds remain supported:

```sh
.venvs/hub/bin/python -m harden.live compile \
  'A hidden-number game with higher/lower feedback over seven turns'
```

## Retrieval flow

1. Load public environment, invariant and similarity-edge rows from the hosted
   SpacetimeDB service. A service failure is explicit; live audits do not silently
   switch to a local store. The CLI may explicitly select a snapshot/SQLite source.
2. Exclude the target's own invariants, seeds, missing parents and incomplete records.
3. Serialize only stable IDs, title, mechanism, preconditions and defense. Raw exploit
   completions, evidence files, private vectors and API credentials are not indexed.
4. Build a content-addressed **local Moss session** with `moss-minilm` and
   `auto_load_on_init=False`. No cloud index is created or uploaded. Snapshots live in
   `.cache/moss-retrieval/`, partitioned by project hash and document fingerprint.
   A changed/deleted record produces a new fingerprint, so stale documents are not
   reused. Unchanged snapshots restore the disk index; invalid caches rebuild.
5. Construct a bounded query from the task and relevant reward/parser methods. Moss
   performs hybrid retrieval (`alpha=0.65`, minimum relevance `0.20`). The SDK embeds
   and searches locally after initialization. Thresholds are configuration defaults,
   not calibrated probabilities or proof of applicability.
6. Expand one graph hop from Moss matches, discounting each propagated score by
   `0.5 * similarity`. Excluded records cannot anchor graph expansion. Zero-score
   results never fill unused slots. Return at most five records with stable ordering.
7. Resolve IDs against the authoritative snapshot, not search-result text. Unknown
   IDs or invalid scores are errors. Bound the model context and record exactly which
   IDs were actually offered. Both hacker and fixer receive this untrusted context.
8. Measure attacks and repairs with the existing target-specific replay gates.
   Retrieval scores and similarity edges never establish that a defense works.

The authoritative snapshot is still downloaded at audit startup. This integration
improves candidate ranking; it does not eliminate whole-store snapshot loading or
implement a persistent global indexing daemon.

## Failure behavior and observability

Missing credentials, missing/wrong SDK, invalid numeric settings, timeouts and Moss
failures stop retrieval explicitly. They never trigger keyword-only retrieval or
silent empty context. A genuine empty eligible store or no relevant matches is a
valid empty result. Provider error text is not echoed, to avoid exposing credentials.

Retrieval receipts record backend (`moss+graph`), embedding model, snapshot hash,
source, target ID, document count, cache state, index-ready/query/total timings,
relevance thresholds, ranked candidate IDs and actual prompt IDs. GameAudit saves
its receipt in the audit report; the generated single-turn pilot and Hub audits
write retrieval JSON beside their evidence. Inspect `hardening_report['retrieval']`
for the episode path. Older checked-in pilots predate Moss and must not be presented
as Moss benchmarks.

Environment settings:

```dotenv
MOSS_ALPHA=0.65
MOSS_MIN_SCORE=0.20
MOSS_TIMEOUT_SECONDS=120
```

## Validation

Tests use the real pinned SDK's document/query types with fake client/session
transport. They cover eligibility, semantic-result routing, graph expansion,
cache reuse/invalidation/deletion, corruption recovery, bounded prompts, no-match
behavior, invalid scores/IDs, missing credentials, timeouts and closure, key redaction,
validated transfer, and context reaching both roles of the multi-turn auditor.

A live Moss authentication/search check remains pending until project credentials
are added. There has been no live quality comparison or latency benchmark yet.

Official references:
- https://docs.moss.dev/docs/start/quickstart
- https://docs.moss.dev/docs/reference/python/api
- https://docs.moss.dev/docs/integrate/sessions

Final offline validation: **208 Python tests and 15 subtests passed**, including
33 Moss-specific cases. One opt-in Hub runtime check was skipped. The existing
hosted graph and dashboard remain reachable. The retrieval CLI correctly reports
missing Moss credentials before making any LLM call. Live Moss validation is pending.

# Live pilot

Work branch: `rishab/live-pipeline-dashboard`.

## Configuration

Put the Anthropic key in the repository root `.env`:

```dotenv
ANTHROPIC_API_KEY=your-key-here
MOSS_PROJECT_ID=your-project-id
MOSS_PROJECT_KEY=your-project-key
```

The file is ignored by Git. Never put the key in the dashboard, a `VITE_` variable,
source code, or chat. `config/pilot.env.example` documents public configuration.
The local Spacetime writer credential is configured separately; a new checkout needs
its own authorized writer token. See `deployment/README.md`.

All default model roles use `claude-haiku-5-5`, low effort and bounded output.
There is no automatic upgrade to a more expensive model, automatic API retry, or
hard dollar stop. `AUDIT_BUDGET_WARNING_USD=2` only warns and continues.
`AUDIT_HARD_CAP_USD` is blank (disabled). Request and settled costs are recorded in
`results/spend_ledger.jsonl`; unsettled reservations are estimates, not invoices.
Rounds are intentionally finite so a pilot cannot loop indefinitely.

## Run locally

Install the pilot runtime in a new checkout (Python 3.13):

```sh
uv venv .venvs/hub --python 3.13
uv pip install --python .venvs/hub/bin/python -r requirements-pipeline.txt
npm ci --prefix dashboard
cp config/pilot.env.example .env
```


```sh
cd /Users/rvempati/loophole
.venvs/hub/bin/python -m harden.live doctor --remote
.venvs/hub/bin/python -m harden.live start
```

Keep the service supervisor running. It starts the database writer and the
frontend if needed; it does not run models. The dashboard is at
http://127.0.0.1:5173/. The hosted database is
`loophole-knowledge-calhacks-2026` on Maincloud. Local processes must remain running
for new local results to sync; this is not a remotely deployed compute worker.

In another terminal, after adding the key:

```sh
cd /Users/rvempati/loophole
# One real open-source Hub environment, two hacker/fixer rounds:
.venvs/hub/bin/python -m harden.live hub primeintellect/reverse-text --rounds 2

# Generate, audit and harden an in-house game; both kinds are supported:
.venvs/hub/bin/python -m harden.live compile 'Guess a hidden number from 1 to 40 in 7 turns with higher/lower feedback'
```

Start with one of these jobs at a time and inspect its result before expanding.
Do not interpret a count of zero exploits as a pipeline failure: findings must be
measured, never guaranteed. These commands run downloaded Prime Intellect Hub
environments locally; they do not rent Prime cloud instances.

## Pipeline

1. The Hub path loads the original installed environment and dataset. It scores
   reference completions and obtains independently checked model-authored benign
   answers. The compiler path asks Haiku to produce a Game module and runs its
   validation gates. Generated games run through OS isolation (macOS sandbox-exec or Linux
   bubblewrap). The multi-turn path replays reply sequences against fresh seeded
   episodes, including environment feedback, and validates repairs against benign episodes.
2. Required Moss hybrid retrieval ranks eligible invariant records loaded from hosted
   SpacetimeDB, then expands one graph hop. Retrieval excludes the current target and
   seeds. Both roles receive bounded untrusted context. Missing credentials or Moss
   failures stop the audit explicitly; there is no keyword fallback. See `MOSS_RETRIEVAL.md`.
3. Haiku proposes candidate reward loopholes. Actual reward replay and an independent
   correctness check distinguish false positives from unusual valid answers. The
   Hub path uses deterministic answer checks first, with a separate verifier role
   for unresolved cases. Generated games use the strict answer parser as their oracle.
4. Confirmed failures are saved with evidence and mechanism metadata. Haiku extracts
   a reusable invariant. A repair is accepted only after replay checks that legitimate
   answers still pass and the observed failures stop passing. Generated target rule
   applications record the source rule IDs and replay evidence.
5. SQLite is the durable local outbox. The writer pushes parents before children,
   preserves failed writes for retry, computes free local 384-dimensional MiniLM
   embeddings, and invokes graph updates. Unchanged rows do not trigger remote writes.
6. The dashboard subscribes directly to the hosted SpacetimeDB tables over WebSocket.
   New findings and graph changes appear as the writer publishes them. Evidence lives
   under `results/evidence/`; the dashboard is a graph viewer, not a paid-job scheduler.

## Validation and limits

Before a paid run, the hosted read endpoint and dashboard responded successfully;
MiniLM produced a 384-dimensional vector; the real reverse-text dataset loaded
1,000 examples and its reference completion earned 1.0 from the actual grader.
The Python regression suite passed 117 tests plus 10 subtests, and the dashboard
passed 4 tests and its production build. The warning regression explicitly spends
more than $2 in a fake ledger and verifies another request proceeds.

## Completed model-driven pilot

`results/evidence/game/ai-cea6b0be598a/` contains the real Haiku pilot.
The generated original and repaired modules are retained under `compiled/` for
replay of this specific run. No Prime Intellect model pilot was run.

- One generated single-turn quotient/remainder arithmetic game.
- Two replay-confirmed conflicting-answer cases scored 1.0 originally, 0.0 after repair.
  They are two instances of the same multi-answer family, not two independent mechanisms.
- All 20 reference completions retained reward 1.0; task generation was unchanged.
- A second hacker round tested the repaired source; no new passing false positive was confirmed.
- One prior calibration invariant was retrieved and its application recorded as blocked.
- Seven Haiku calls across compiler and audit roles: estimated usage cost $0.0053688.
  `model_spend_usd` in the per-environment result excludes compiler calls; the shared ledger includes both.
- Hosted publication completed with 6 pushed rows and 0 errors. Public reads then showed
  4 environments, 5 invariant records, and 1 similarity edge. Three environments remain
  scripted calibration data, separately labeled in the dashboard.

The compiler intentionally introduces a loose-parser weakness. This demonstrates
model generation, attack discovery, repair, replay, retrieval and publication;
it is not evidence of discovering an unanticipated real-world vulnerability.
The strict-parser oracle shares the generated checker and is not an external proof.

The dashboard always shows the entire store. Blue nodes are environments; amber
nodes are invariant records inside shaded rule-family regions. Solid lines show
provenance, dashed green arrows measured transfer, and dotted purple lines embedding
similarity. Clicking nodes focuses evidence without filtering the store. Screenshot:
`docs/knowledge-graph-clusters.png`.

`harden.audit.loop` is the full upstream acceptance-oriented audit implementation.
The bounded live Hub command uses `harden.audit.pilot_loop`; it is not a replacement
for the full leaderboard workflow. Only reverse-text has had a local runtime smoke
check. Other Hub environments need their declared runtimes. No Hub paid pilot or
full leaderboard certification is claimed by this PR.

## Multi-turn integration after main PR #4

Latest main `f2ca0f8` is integrated. The live compile entry point permits multi-turn
output and routes the compiler's sandbox-verified `kind` to the appropriate audit.
Multi-turn games use `harden.game_audit`, whose hacker proposes reply sequences and
whose fixer patches the episode reward. The standalone pipeline also supports
multi-turn hardening, training and replay. Its hard dollar cap is now opt-in, not $3 by default.

A new real Haiku pilot generated `compiled/game_852c07fa.py` (higher/lower, 1–40,
up to seven guesses). Three first-round attack cases earned 1.0 under the loose
reward and 0.0 under the strict episode oracle; the accepted repair reduced all
three to 0.0. All 16 benign/reference variants passed. Reference transcripts took
5, 5 and 4 actual turns. A second hacker round yielded no new confirmed false positive.
The pilot retrieved from hosted SpacetimeDB, emitted three invariant records, and
published successfully. Eight Haiku calls cost an estimated $0.00799367, including
both compilation calls. This is a planted-parser demo; the cases are related
variants rather than three independent defenses.

See `results/evidence/game/multiturn-higher-lower-40/` for the audit, replay,
usage and source artifacts. The older single-turn evidence above remains historical
and reproducible. The graph includes both pilots and all calibration records.

### Remaining work for the complete demo

1. Obtain the actual multi-turn GPU checkpoints, metrics and rollout JSON from the
   training machine. Main contains code and reported results, but those artifacts
   are not present locally. Reproduce or verify the hardened-versus-hacked training
   comparison before presenting it as this checkout's measured performance.
2. Generate the dashboard's training replay from those real rollout files. The
   current `/replay.html` is still the explicit no-training-replay placeholder.
3. Connect training metrics and job progress to the dashboard. The graph has live
   subscriptions, but does not yet launch/schedule full training jobs or chart their metrics.
4. Add source invariant IDs and target-specific rule-application records to the new
   episode auditor. It retrieves context and publishes newly extracted invariants;
   unlike the older single-turn pilot, it does not yet attribute measured transfers
   to each retrieved rule.
5. Keep services alive on the chosen demo machine or deploy compute/frontend for a
   public demo. Only the hosted knowledge store is independently running remotely.
6. Moss retrieval is now required and implemented. Add the project ID/key, run the
   retrieval-only check, then measure retrieval quality; older pilot evidence predates Moss.

Final validation: 175 Python tests + 15 subtests passed; one opt-in Hub smoke check
was skipped. Dashboard: 4 tests and production build passed. SpacetimeDB: 65 tests
passed. No GPU training or Prime Intellect paid run was performed during this update.

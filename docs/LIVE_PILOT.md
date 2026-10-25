# Live pilot

Work branch: `rishab/live-pipeline-dashboard`.

## Configuration

Put the Anthropic key in the repository root `.env`:

```dotenv
ANTHROPIC_API_KEY=your-key-here
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

# Separately: generate, audit and harden an in-house compiled game:
.venvs/hub/bin/python -m harden.live compile 'A single-turn numeric deduction game'
```

Start with one of these jobs at a time and inspect its result before expanding.
Do not interpret a count of zero exploits as a pipeline failure: findings must be
measured, never guaranteed. These commands run downloaded Prime Intellect Hub
environments locally; they do not rent Prime cloud instances.

## Pipeline

1. The Hub path loads the original installed environment and dataset. It scores
   reference completions and obtains independently checked model-authored benign
   answers. The compiler path asks Haiku to produce a Game module and runs its
   validation gates. Generated games run in a macOS OS sandbox with network and
   subprocess creation denied; other operating systems need a container runner.
2. Public SQL reads retrieve knowledge from other environments. Retrieval excludes
   the current target. Retrieved text is labeled untrusted context, and does not
   establish that a rule applies to the target.
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

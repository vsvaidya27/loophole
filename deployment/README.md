# Hosted knowledge graph handoff

The branch is published to SpacetimeDB Maincloud before merging the PR. Public connection
metadata is in `maincloud.json`; it contains no tokens. Maincloud serves the database
independently of the developer's laptop. The free tier can sleep when idle and wake on
requests. No seed data, audit data, continuous polling, or model workloads were enabled.

Setup verification on October 24, 2026: environment, exploit, invariant, rule,
similarity_edge, rule_application, and rule_title tables contained zero rows. Only access
metadata and the default graph configuration were initialized. A dedicated writer
successfully called `rebuild_graph`; an anonymous caller was rejected. The real module
was built and published with SpacetimeDB CLI 2.13.0.

## Varun: connect and push

Use these values on the machine that runs the audit:

```sh
export SPACETIME_HOST=https://maincloud.spacetimedb.com
export SPACETIME_DB=loophole-knowledge-calhacks-2026
export SPACETIME_TOKEN_FILE=/private/path/to/knowledge-writer-token
python3 -m harden.store.service_client push audit-batch.json
```

The dedicated writer token is stored on the owner's machine at
`/Users/rvempati/loophole/.spacetime-varun-token` with mode 600 and is gitignored. Transfer
it privately to Varun; do not put it in the PR, an issue, or a shared log. No message or
credential has been sent to Varun automatically. This credential can write graph/core
records but cannot grant writers or republish the database.

`ServiceClient(host, database, token).call(reducer, **fields)` also supports individual
writes. It sends positional JSON in the existing reducer order. `push(batch)` takes the
same shape as `fixtures/invariants.sample.json`: `environments`, `entries` (each with
`env_id`, `exploit`, `invariant`, optional `embedding_model` and `embedding`), and
`applications`. It writes dependencies in order, triggers `graph_on_invariant`, and
propagates failures. Retrying the same IDs is safe. The client does not watch SQLite or
mark rows pushed; that remains the pusher's job. Empty embeddings still create rule
memberships, but similarity edges require compatible vectors.

Public reads need no token. Retrieval uses `SPACETIME_TOKEN` only when supplied; the
writer CLI also supports the token file variable. On the owner's Python installation,
HTTPS needed `SSL_CERT_FILE=/etc/ssl/cert.pem` because its default CA location was absent.
Certificate verification remained enabled. Other machines should use their normal CA
configuration.

## Dashboard

Connect to `wss://maincloud.spacetimedb.com` and database
`loophole-knowledge-calhacks-2026`, using the SDK's normal connection builder and generated
bindings in `dashboard/src/module_bindings/`. The frontend must install `spacetimedb@2.13.0`. Feed the subscribed rows into `dashboard/src/graph/buildGraph.ts`.
Database dashboard: https://spacetimedb.com/loophole-knowledge-calhacks-2026

## Administration

The signed-in publishing account owns the database. Every core and graph write reducer
requires publisher or approved-writer access. Tables stay publicly readable as designed.
`init` creates the private owner metadata on first publish; existing databases created
before this access layer need an explicit migration rather than an unguarded bootstrap.

Manage a writer from the publishing account (identity is public; token stays private):

```sh
spacetime call --no-config --server maincloud loophole-knowledge-calhacks-2026 \
  set_writer '"<64-character-lowercase-identity>"' true
# Use false to revoke.
```

Republish deliberately from a reviewed checkout, preserving data:

```sh
spacetime publish loophole-knowledge-calhacks-2026 --server maincloud \
  --module-path spacetimedb --delete-data=never
```

`--no-config` is necessary for CLI calls with an explicit database because the local
`spacetime.json` otherwise supplies `loophole` as the call target. The repo's local default
was preserved. Do not run multiple branches publishing over this shared database.

This service is deployed. The setup checks above describe its initial empty state;
subsequent calibration and the real Hub audit import are recorded below. Continuous
outbox synchronization is configured separately from a one-time batch import.

## Subsequent live calibration

The service is no longer empty: the scripted compiler calibration `scripted-20261024`
was explicitly published during live-dashboard verification. It contains 3 game
environments, 3 per-environment multi-answer exploit instances/invariants, one shared
class rule, and 2 cross-game transfer outcomes. These are measured scripted results
against planted compiler-library loopholes, not model-discovered Hub exploits. See
`docs/LIVE_DEMO_STATUS.md` and `results/compiler_pilot/scripted-20261024/report.json`.

## Verified Hub audit ingestion

On October 24, 2026 (Pacific), the approved machine identity
`c200e3f089f4629da3c7fb91dcc9e0268a3988f480f036474c08b51f2410353b` published
`results/invariant_graph_batch.json` to the Maincloud database above using its existing
CLI login credential in memory. No credential was persisted in this repository.

The import contains 19 environments and 95 invariants with normalized MiniLM embeddings,
with 60 exploits marked patched and 35 still confirmed/open. All batch fields and rewards
were read back, graph memberships verified, and the public cosine scores checked for
423 audit-to-audit edges. All 95 audit nodes have similarity edges. Hosted graph retrieval
successfully returned audit knowledge. The complete receipt is
[`results/audit_batch/spacetime_ingestion.json`](../results/audit_batch/spacetime_ingestion.json).

The batch includes no cross-environment transfer outcomes. Repair source and replay
files remain in Git; hosted rows carry defense patterns and evidence paths. This import
did not change the checkout's local-server default or mark local SQLite outbox rows
pushed. Frontend subscriptions and graph RAG can read the Maincloud records immediately.

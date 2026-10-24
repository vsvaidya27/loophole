# Invariant store plan

> **DRAFT, under review.** Safe to read and plan from. A verified version follows within
> the hour and may change file layout, hook signatures or a column or two. Hold off on
> code that depends on exact signatures until then.

Status: plan, nothing built yet. Written Sat Oct 24, 2026 against SpacetimeDB 2.13.0.
Owners: Varun (store, write path), Rishab (invariant graph), Anirudh (dashboard view).

Every confirmed reward hack becomes an **invariant**: a reusable rule saying how the hack
works, why the reward allowed it, when it applies, and how to defend against it. The store
keeps those rules, groups them into a graph, and hands them back when a new environment
needs pre-hardening. It is beat 2 of the demo (the invariant graph) and the memory behind
beat 3 (stored rules pre-harden the judge's game).

This doc is the contract between the people building it. If you need to change a table,
a reducer signature or a hook, change it here first and tell the others, because
SpacetimeDB cannot change existing columns without wiping data (see Gotchas).

## Decisions

1. **SpacetimeDB is the live database.** One database, `loophole`, running a
   **TypeScript** module. TypeScript because the dashboard is React and shares the
   generated types, because it needs no Rust/wasm toolchain, and because it is out of
   beta in 2.x. SpacetimeDB has no Python module language and no maintained Python SDK.
2. **The graph is computed inside the database.** When an invariant lands, a reducer
   computes its similarity edges and rule membership in the same transaction, so the
   dashboard always sees a consistent graph. This is also what the SpacetimeDB prize
   asks for: SpacetimeDB as the core real-time backend, "not just added on the side".
3. **Python writes over HTTP and React reads by subscription.** The hardening engine
   calls reducers with `POST /v1/database/loophole/call/<reducer>`. The dashboard
   subscribes with the `spacetimedb` npm SDK and re-renders on every insert.
4. **`invariants.db` (SQLite) stays as the local mirror.** The leaderboard checker
   (`scripts/check_leaderboard.py`) reads `invariants.db` and must not change. Every
   write goes to SQLite first, then SpacetimeDB. If SpacetimeDB is down or gets wiped,
   `python -m harden.store sync` rebuilds it from the mirror. This also covers the
   wifi-on-stage risk in the build plan.
5. **Embeddings are computed in Python.** Default model: sentence-transformers
   `all-MiniLM-L6-v2` (384 floats, L2-normalized, runs on CPU, no API key). Vectors are
   stored in a private table that only module code reads, so dashboard clients never
   download them. SpacetimeDB has no vector index (issue #5376 is open), so similarity
   is a brute-force cosine, which is trivial at our scale (hundreds of rows).
6. **Run locally by default.** `spacetime start` on the demo laptop. Maincloud is
   optional and only needed if we want a public URL; nothing in the prize rules
   requires it.

## Who owns what

| Piece | Owner | Lives in |
| --- | --- | --- |
| Core tables and write reducers (`environment`, `exploit`, `invariant`, `invariant_embedding`, `rule_application`) | Varun | `spacetimedb/src/core_tables.ts`, `spacetimedb/src/core.ts` |
| Python client, SQLite mirror, invariant extraction (Claude), embeddings, retrieval, seed and sync commands | Varun | `harden/store/` |
| Graph tables and graph logic (`graph_config`, `similarity_edge`, `rule`, `rule_member`, the hooks below) | Rishab | `spacetimedb/src/graph_tables.ts`, `spacetimedb/src/graph.ts` |
| `buildGraph(rows) → {nodes, edges}`, the pure function that turns subscribed rows into a drawable graph | Rishab | `dashboard/src/graph/buildGraph.ts` |
| Rendering the graph and live updates | Anirudh | `dashboard/` |

Rule of thumb: each person writes only their own tables. Rishab's code may read the core
tables but never writes them; core code calls Rishab's hooks and never touches graph
tables directly.

## Data flow

```
hardening engine (Python)
  │  exploit confirmed by the judge
  ├─► record_exploit ───────────────────────────────┐
  │  Claude extracts the invariant, MiniLM embeds it │
  ├─► invariants.db (SQLite mirror, checker reads)   │  HTTP /call
  └─► record_invariant ─────────────────────────────►│
                                                     ▼
                         SpacetimeDB module "loophole" (TypeScript)
                           core.ts: upsert rows, then call
                           graph.ts: onInvariantRecorded(ctx, invariant_id)
                             → similarity_edge rows, rule / rule_member rows
                                                     │  live subscription
                                                     ▼
                         dashboard: useTable(...) → buildGraph(rows) → render

new environment (hub env or the judge's game)
  └─► retrieve(reward source + task) → top invariants → fixer pre-hardens
      → record_rule_application(invariant_id, target_env_id, outcome)
      → the graph shows a transfer edge
```

## Module layout

```
spacetimedb/                  SpacetimeDB module, database "loophole"
  spacetime.json              {"database": "loophole", "module-path": ".", "server": "local",
                               "generate": [{"language": "typescript",
                                             "out-dir": "../dashboard/src/module_bindings"}]}
  package.json, tsconfig.json
  src/
    index.ts                  export { default } from './schema'; export * from './core'; export * from './graph';
    schema.ts                 const spacetimedb = schema({ ...coreTables, ...graphTables }); export default spacetimedb;
    core_tables.ts            Varun
    core.ts                   Varun: reducers + init
    graph_tables.ts           Rishab
    graph.ts                  Rishab: hooks + graph reducers
    *.test.ts                 vitest, using spacetimedb/server/test-utils (no server needed)
```

Splitting a TypeScript module across files this way is supported (2.7 added `onSchedule`
specifically so split modules work), but M0 must confirm that reducers re-exported from
`index.ts` get registered. If they don't, fall back to one `index.ts` with clearly marked
"core" and "graph" sections.

Naming: table names are set explicitly in snake_case, column keys are snake_case, and
reducers are exported as snake_case consts (`record_invariant`). That makes the names
Python and SQL use identical to the source. The generated TypeScript client shows
columns in camelCase (`env_id` → `envId`, `invariant_id` → `invariantId`).

## Core tables (Varun)

Starting definition. Columns cannot be renamed or reordered later without wiping data,
so review this now.

```ts
// spacetimedb/src/core_tables.ts
import { table, t } from 'spacetimedb/server';

export const environment = table({ name: 'environment', public: true }, {
  env_id: t.string().primaryKey(),        // hub id "owner/name", or "game/<slug>", or "test/<name>"
  source: t.string(),                     // 'hub' | 'game' | 'test'
  title: t.string(),
  status: t.string(),                     // 'queued' | 'running' | 'patched' | 'robust' | 'failed_to_run'
  updated_at: t.timestamp(),
});

export const exploit = table({ name: 'exploit', public: true }, {
  invariant_id: t.string().primaryKey(),  // `${env_id}#${exploit_id}`, shared with invariant
  env_id: t.string().index('btree'),
  exploit_id: t.string(),                 // same id as results/leaderboard.json
  exploit_class: t.string(),              // taxonomy below
  iteration: t.u32(),                     // hardening iteration that found it (1..5)
  summary: t.string(),                    // one line for the dashboard
  sample_completion: t.string(),          // the hack itself, truncated to 2000 chars
  reward_original: t.f32(),               // reward the hack earned before the patch
  reward_patched: t.option(t.f32()),      // set once a patch is accepted
  status: t.string(),                     // 'confirmed' | 'patched'
  evidence_path: t.string(),              // repo-relative replay file
  confirmed_at: t.timestamp(),
});

export const invariant = table({ name: 'invariant', public: true }, {
  invariant_id: t.string().primaryKey(),
  env_id: t.string().index('btree'),
  exploit_id: t.string(),
  exploit_class: t.string().index('btree'),
  title: t.string(),                      // <= 80 chars, used as the node label
  mechanism: t.string(),                  // how the hack works
  root_cause: t.string(),                 // why the reward allowed it
  preconditions: t.string(),              // when the rule applies to another environment
  defense_pattern: t.string(),            // how to block it
  tags: t.array(t.string()),              // e.g. ['parser:xml', 'answer:numeric', 'match:substring']
  evidence_path: t.string(),
  created_at: t.timestamp(),
});

// Private: only module code reads vectors, so dashboard clients never download them.
export const invariant_embedding = table({ name: 'invariant_embedding' }, {
  invariant_id: t.string().primaryKey(),
  model: t.string(),                      // 'all-MiniLM-L6-v2'
  vector: t.array(t.f32()),               // 384 floats, L2-normalized
});

export const rule_application = table({ name: 'rule_application', public: true }, {
  id: t.u64().primaryKey().autoInc(),
  invariant_id: t.string().index('btree'),  // the invariant whose defense was applied
  target_env_id: t.string().index('btree'),
  outcome: t.string(),                    // 'pre_hardened' | 'blocked' | 'not_blocked' | 'not_applicable'
  detail: t.string(),
  created_at: t.timestamp(),
});

export const coreTables = { environment, exploit, invariant, invariant_embedding, rule_application };
```

Strings are used for `source`, `status`, `outcome` and `exploit_class` instead of
SpacetimeDB enums because Python then sends plain JSON strings. The reducers validate
the allowed values.

### Exploit classes

These are the initial values of `exploit_class`. The extraction prompt picks exactly one,
and rule clustering only merges invariants that share a class. Add a value here before
using it.

| exploit_class | Meaning |
| --- | --- |
| `substring-match` | Answer accepted if it appears anywhere in the output |
| `multi-answer` | Several candidate answers; the parser credits any of them |
| `format-only` | Reward for tags or format without a correct answer |
| `parser-bypass` | Unusual markup (nested, empty or duplicated tags) confuses the parser |
| `lenient-normalization` | Numeric or string normalization accepts wrong values |
| `constraint-gaming` | Length, keyword or constraint checks satisfied without doing the task |
| `answer-leak` | Answer recoverable from the prompt or metadata |
| `judge-manipulation` | Text that steers an LLM judge |
| `other` | Anything else (say what in `mechanism`) |

## Reducers (Varun)

Python calls these over HTTP with a **positional JSON array** in exactly the order
listed. Timestamps are set inside the reducer from `ctx.timestamp`, and Python never
sends them. Every write is an idempotent upsert, so retries are safe (since 2.13 an HTTP
call can return 504 "outcome unknown").

| Reducer | Arguments, in order | Effect |
| --- | --- | --- |
| `record_environment` | env_id, source, title, status | Upsert `environment` |
| `record_exploit` | env_id, exploit_id, exploit_class, iteration, summary, sample_completion, reward_original, evidence_path | Upsert `exploit` with status 'confirmed' |
| `mark_exploit_patched` | invariant_id, reward_patched | Set reward_patched and status 'patched' |
| `record_invariant` | env_id, exploit_id, exploit_class, title, mechanism, root_cause, preconditions, defense_pattern, tags, evidence_path, embedding_model, embedding | Upsert `invariant` and `invariant_embedding`, then call `onInvariantRecorded(ctx, invariant_id)` |
| `record_rule_application` | invariant_id, target_env_id, outcome, detail | Insert into `rule_application` |
| `clear_environment` | env_id | Delete the environment's exploits, invariants, embeddings and applications, then call `rebuildGraph(ctx)` |
| `init` (lifecycle) | none | Call `graphInit(ctx)` |

Validation in `record_invariant` (throw `SenderError`, which rolls back the whole call):
the matching `exploit` row exists; mechanism, root_cause, preconditions and
defense_pattern are each at least 10 characters (the checker's rule); exploit_class is in
the taxonomy; the embedding has 384 finite values.

Auth: none for local development. Before any Maincloud deploy, add a private `writer`
allowlist table checked against `ctx.sender`, since anyone can call public reducers.

## Graph (Rishab)

### Hooks core calls

These are plain functions exported from `graph.ts`. Core calls them inside its own
reducers, so graph updates commit in the same transaction as the invariant. M0 ships
no-op versions so the module builds; Rishab replaces them.

```ts
export function graphInit(ctx): void
// Insert the single graph_config row if it is missing.

export function onInvariantRecorded(ctx, invariantId: string): void
// The invariant and its embedding rows already exist. Must be idempotent: the same
// invariant can be re-recorded after an edit. Suggested algorithm:
//   1. delete similarity_edge rows touching invariantId (filter on a_id and b_id)
//   2. cosine against every other invariant_embedding (vectors are normalized, so a dot product)
//   3. insert edges with score >= graph_config.edge_threshold, with a_id < b_id
//   4. rule: join the rule of the most similar invariant with the same exploit_class if
//      score >= rule_threshold, otherwise create a rule (title and defense_pattern copied
//      from this invariant); update member_count and env_count

export function rebuildGraph(ctx): void
// Clear similarity_edge, rule and rule_member, then replay onInvariantRecorded over
// invariants sorted by (created_at, invariant_id). The same input always gives the
// same graph.
```

Reducers must be deterministic: no `Math.random`, no network, no module-level state.
Use `ctx.random()` if randomness is ever needed.

### Graph tables (starting point, Rishab to finalize)

```ts
// spacetimedb/src/graph_tables.ts
export const graph_config = table({ name: 'graph_config', public: true }, {
  id: t.u32().primaryKey(),               // always 0
  edge_threshold: t.f32(),                // start 0.55, tune on real data
  rule_threshold: t.f32(),                // start 0.70, tune on real data
});

export const similarity_edge = table({ name: 'similarity_edge', public: true }, {
  id: t.u64().primaryKey().autoInc(),
  a_id: t.string().index('btree'),        // invariant_id, a_id < b_id
  b_id: t.string().index('btree'),
  score: t.f32(),
});

export const rule = table({ name: 'rule', public: true }, {
  rule_id: t.u64().primaryKey().autoInc(),
  title: t.string(),
  exploit_class: t.string(),
  defense_pattern: t.string(),
  member_count: t.u32(),
  env_count: t.u32(),
  updated_at: t.timestamp(),
});

export const rule_member = table({ name: 'rule_member', public: true }, {
  invariant_id: t.string().primaryKey(),  // each invariant belongs to exactly one rule
  rule_id: t.u64().index('btree'),
});

export const graphTables = { graph_config, similarity_edge, rule, rule_member };
```

Graph reducers for tuning from the CLI: `rebuild_graph()`,
`set_graph_config(edge_threshold, rule_threshold)` (which then rebuilds), and
`set_rule_title(rule_id, title)` (lets a Python helper give rules nicer LLM-written names
later).

The starting thresholds are guesses for MiniLM sentence similarity. Tune them on the seed
data, then on real invariants.

### What the dashboard draws

`buildGraph` turns subscribed rows into nodes and edges. It is a pure function, so
Rishab can unit-test it with fixture rows and Anirudh only renders its output.

```ts
type GraphNode =
  | { id: `env:${string}`;  kind: 'environment'; label: string; source: string; status: string }
  | { id: `inv:${string}`;  kind: 'invariant';   label: string; exploitClass: string; envId: string }
  | { id: `rule:${string}`; kind: 'rule';        label: string; memberCount: number; envCount: number };

type GraphEdge = {
  id: string;
  kind: 'found_in' | 'instance_of' | 'similar_to' | 'applied_to';
  source: string;            // node id
  target: string;            // node id
  weight?: number;           // similar_to: cosine score
  outcome?: string;          // applied_to: rule_application.outcome
};
```

| Edge | From rows | Meaning |
| --- | --- | --- |
| `found_in` | `invariant.env_id` | invariant → the environment it was learned on |
| `instance_of` | `rule_member` | invariant → its rule |
| `similar_to` | `similarity_edge` | invariant ↔ invariant, weight = score |
| `applied_to` | `rule_application` | rule of the invariant → target environment ("transferred"; `blocked` is the money shot for beat 3) |

Rows of environments with `source = 'test'` come from the seed and should be hideable.
`rule_id` is a u64, which is a `bigint` in the TS SDK, so stringify it for node ids.

## Python side (Varun)

`harden/store/`, configured from `.env`: `SPACETIME_HOST` (default
`http://127.0.0.1:3000`), `SPACETIME_DB` (default `loophole`), `SPACETIME_TOKEN`
(minted once with `POST /v1/identity` and reused, so the writer keeps one identity).

```python
record_environment(env_id, *, source, title, status)
record_exploit(env_id, exploit_id, *, exploit_class, iteration, summary,
               sample_completion, reward_original, evidence_path)
mark_exploit_patched(env_id, exploit_id, *, reward_patched)
extract_invariant(evidence) -> Invariant   # Claude call with a JSON schema; picks exploit_class
record_invariant(inv: Invariant)           # embed, write SQLite, then call the reducer
record_rule_application(invariant_id, target_env_id, outcome, detail)
retrieve(query_text, k=5, exploit_class=None) -> list[Match]
clear_environment(env_id)
```

CLI: `python -m harden.store seed | sync | export-graph | doctor`.

- **Write order.** SQLite first, then SpacetimeDB. If the HTTP call fails, log it and keep
  going: the audit must not stop because the live database is down. `sync` replays the
  mirror into SpacetimeDB (idempotent), then calls `rebuild_graph`.
- **SQLite mirror (`invariants.db`).** It mirrors the core tables. The `invariants` table
  must keep the checker's columns: `env_id, exploit_id, mechanism, root_cause,
  preconditions, defense_pattern, evidence_path`, primary key `(env_id, exploit_id)`, plus
  `exploit_class, title, tags, embedding_model, embedding BLOB, created_at`. The checker
  wants exactly one row per exploit of each patched leaderboard entry and none for robust
  ones; rows for other environments (live games) are ignored. Open it in WAL mode with a
  busy timeout, because audit workers run in parallel.
- **Seed data goes to SpacetimeDB only**, never the mirror, so test rows can't leak into
  the leaderboard check.
- **Retrieval reads the SQLite mirror**: embed the new environment's reward source and
  task, take the top-k by cosine, then ask Claude which preconditions actually apply. It
  works even when SpacetimeDB is down. Stretch goal: move it into a SpacetimeDB procedure.
- **Embedding text**: `f"{title}. {mechanism} {preconditions} {defense_pattern}"`.

## Seed data (unblocks Rishab now)

`fixtures/invariants.sample.json` has about 12 realistic invariants across 6
`test/...` environments. Several share an exploit class (for example three
`substring-match` invariants from different math environments), so rules and similarity
edges actually form. `python -m harden.store seed` embeds them and writes them through
the same reducers. Until M0 lands, Rishab can build `graph.ts` and `buildGraph.ts` against
the table definitions above with the vitest harness, with no server and no seed needed.

## Milestones

| | What | Who | Unblocks |
| --- | --- | --- | --- |
| M0 | Module skeleton with core tables, core reducers and no-op graph hooks, published locally; `harden.store` client; seed fixture; this contract confirmed by a real publish (checklist below) | Varun | everyone |
| M1 | Graph tables, `onInvariantRecorded`, `rebuildGraph`, tuning reducers, and `buildGraph` working on seed data with vitest tests | Rishab (can start now) | M3 |
| M2 | Hub audit writes real exploits and invariants as they are confirmed; mirror passes the leaderboard checker | Varun | beat 2 |
| M3 | Dashboard renders the live graph and highlights new nodes as they arrive | Anirudh | beat 2 |
| M4 | Retrieval pre-hardens the judge's game, and `rule_application` rows show transfer edges | Varun, Rishab, Rohan | beat 3 |
| M5 | Optional Maincloud deploy with the writer allowlist; record the live-update footage for the Devpost video | Varun | prize |

The build plan cuts the graph visualization first if we fall behind. The store (M0, M2) and
retrieval (M4) still stand on their own and can be shown as a list.

### M0 verification checklist

Nothing in this doc has been compiled yet. These come from the 2.13 docs and source and
must be confirmed on the first publish:

- [ ] Reducers re-exported from `index.ts` (`export * from './core'`) are registered.
- [ ] `t.array(t.string())` and `t.array(t.f32())` work as reducer arguments over HTTP
      (a JSON array of strings and a JSON array of numbers).
- [ ] `reward_patched` as `t.option(t.f32())`: Python sends `{"some": 0.0}` or `{"none": []}`.
- [ ] Positional HTTP arguments follow the declared order of the reducer's argument object.
- [ ] A Python write over HTTP shows up in a React `useTable` subscription.

## Local setup

Each person installs the CLI once (the official installer):

```bash
curl -sSf https://install.spacetimedb.com | sh
```

```bash
spacetime start                          # terminal 1: local server on :3000
cd spacetimedb && npm install
spacetime publish -s local loophole      # always pass -s local, see Gotchas
spacetime generate --lang typescript --out-dir ../dashboard/src/module_bindings --module-path .
spacetime sql -s local loophole "SELECT * FROM invariant"
spacetime logs -s local -f loophole
```

Dashboard connection (2.x API):

```ts
DbConnection.builder()
  .withUri('ws://localhost:3000')
  .withDatabaseName('loophole')
  .withToken(localStorage.getItem(TOKEN_KEY) || undefined)
  .onConnect((_conn, _identity, token) => localStorage.setItem(TOKEN_KEY, token));
// in components: const [rows, isReady] = useTable(tables.invariant);  (from 'spacetimedb/react')
```

## Gotchas (SpacetimeDB 2.x)

- **The CLI's default server is Maincloud**, not local. Pass `-s local` or keep
  `"server": "local"` in `spacetime.json`, or you will publish to the cloud by accident.
- **Schema changes.** Republishing can add tables, indexes and reducers, and can add a
  column only at the end of a table with a `.default(...)`. Renaming, retyping, reordering
  or removing a column needs `spacetime publish -s local loophole --delete-data`, which
  wipes everything (recover with `python -m harden.store sync`). Note the flag's value
  needs `=`: `--delete-data=on-conflict`.
- **Tables are private by default.** Private tables don't appear in generated bindings and
  clients can't subscribe to them. Everything the dashboard reads is `public: true`.
- **Only primary keys have `.update()`.** Look up rows by primary key, then update.
- **SQL is limited.** No ORDER BY, GROUP BY, DISTINCT or LIKE, and one statement per HTTP
  request. Sort in code. Subscriptions always return full rows of a single table.
- **HTTP details.** `Content-Type` must be exactly `application/json` (requests' `json=`
  sets it correctly). A call without a token gets a fresh anonymous identity every time.
  Every HTTP call also runs the `client_connected` and `client_disconnected` hooks, so
  keep those cheap or absent.
- **TS SDK types.** u64 is `bigint`, `option` is `T | undefined`, column names are
  camelCase. In 2.x reducer callbacks for other clients' calls were removed, so drive the
  UI from `onInsert`/`onUpdate`/`useTable`. Rows written by Python arrive with event tag
  `'Transaction'`.
- **Stale examples.** 1.x examples use `withModuleName`, `@clockworklabs/spacetimedb-sdk`
  and `schema(t1, t2)`. In 2.x these are `withDatabaseName`, `spacetimedb`, and
  `schema({ t1, t2 })` as the default export.

## SpacetimeDB prize

$2,048 / $1,024 / $512 ("most impressive use of Spacetime"), listed on the Hive live
site but not yet on Devpost, so ask at the SpacetimeDB workshop (Sat 4–5 PM, Theater)
how to enter. There is no formal rubric beyond SpacetimeDB being the core real-time
backend. What we can show: the graph is computed by reducers in the same transaction as
each write; the dashboard updates live while the hacker runs; rules transfer to a new
environment in front of the judges. Devpost wants a video for sponsors who judge
asynchronously, so record the live updates. The submission deadline is Sun Oct 25,
9:00 AM PDT.

## Open questions

1. **SQLite mirror (Varun).** Keeping both stores is the price of not touching the frozen
   checker. The alternative is exporting SpacetimeDB to SQLite at the end, which breaks if
   the live database is down when we need the results.
2. **Embedding model.** `all-MiniLM-L6-v2` pulls in PyTorch. If that's too heavy, use a
   lighter local model or TF-IDF. The only interface is "384 normalized floats plus a
   model name"; if the dimension changes, update the validation in `record_invariant`.
3. **Prize entry.** Who goes to the 4 PM workshop?

## Sources

SpacetimeDB 2.13.0 docs and source (clockworklabs/SpacetimeDB at 155f305, Oct 23,
2026): tables, column types, indexes, reducers, procedures, views, automatic migrations,
the HTTP API (`/v1/identity`, `/v1/database/:name/call/:reducer`, `/sql`), SATS-JSON, SQL
reference, TypeScript SDK and React integration, unit testing, `spacetime.json`, and the
`chat-react-ts` template. Cal Hacks 13.0: hive.hackberkeley.org (prizes and schedule),
cal-hacks-13-0.devpost.com, and spacetimedb.com/blog/spacetime-at-calhacks.

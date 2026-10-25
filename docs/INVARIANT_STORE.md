# Invariant store plan

Status: **reviewed plan, M0a skeleton in the repo** (Sat Oct 24, 2026, SpacetimeDB
2.13.0). `spacetimedb/` holds the core tables and reducers plus empty graph files, and
`npm test` runs 16 harness tests covering every core reducer and the seed fixture. Two
reviewers independently built the module from an earlier draft under the official 2.13.0
test harness; the layout and types below are what passed. The first real publish,
Python's HTTP calls and the React subscription are still unverified (M0 checklist).

Owners: Rishab (SpacetimeDB module, pusher, invariant graph), Varun (audit-side writes,
extraction, retrieval, transfer test), Anirudh (dashboard view).

## Handoff to Rishab (Sat Oct 24, 04:00)

Done and pushed (commit `45a6445`): the reviewed plan (this doc), the module skeleton in
`spacetimedb/` with all core tables and reducers, the seed fixture with real MiniLM
vectors, the shared exploit-class list, and 16 passing harness tests. Rishab's
`run_id`-keyed `rule_application` and versioned `detail` are in.

Rishab picks up, in this order:

1. **M1, the graph** (no server needed): fill in `graph_tables.ts` and `graph.ts` from the
   Graph section, write `buildGraph` and `fixture.graph.json`, and test with vitest on the
   seed vectors. Start the edge threshold at 0.45.
2. **M0, the first real publish**: install the CLI, `spacetime start`, `spacetime publish`
   from the repo root, and work through the M0 checklist (HTTP calls from Python,
   subscription from React, restart recovery).
3. **The pusher and CLI** in `harden/store/`: the HTTP client, `push --watch`, `sync`,
   `seed`, `replay`, `reset-demo` and `doctor`, as specified under Python side.

Varun keeps the parts that live inside the hardening engine: audit workers writing mirror
rows (and calling `clear_environment` when an env restarts), Claude extraction,
`reconcile` before the leaderboard check, retrieval, and the beat-3 transfer test. The
mirror schema and reducer signatures in this doc are the interface between the two halves;
change them here first.

Check the current state: `cd spacetimedb && npm install && npm test` (Node 22+).

Every confirmed reward hack becomes an **invariant**: a reusable rule saying how the hack
works, why the reward allowed it, when it applies, and how to defend against it. The store
keeps those rules, connects them into a graph, and hands them back when a new environment
needs pre-hardening. It drives beat 2 of the demo (the invariant graph) and beat 3 (stored
rules pre-harden the judge's game).

This doc is the contract between us. If you need to change a table, a reducer signature or
a file boundary, change it here first and tell the others: SpacetimeDB cannot change
existing columns without wiping data.

## Decisions

1. **SpacetimeDB is the live database.** One database, `loophole`, running a
   **TypeScript** module. TypeScript because the dashboard is React and shares the
   generated types, because it needs no Rust/wasm toolchain, and because it is out of beta
   in 2.x. SpacetimeDB has no Python module language and no maintained Python SDK.
2. **The graph is computed by reducers.** Rishab's reducers turn invariants into
   similarity edges and rules inside SpacetimeDB, and the dashboard subscribes. They run
   as their own reducer calls, not inside the core write, so a graph bug can never block
   or roll back an invariant. This is also what the SpacetimeDB prize asks for:
   SpacetimeDB as the core real-time backend, "not just added on the side".
3. **The audit writes SQLite; one pusher writes SpacetimeDB.** Audit workers only write
   rows to `invariants.db` (standard library, no torch, no network). A single long-lived
   process, `python -m harden.store push --watch`, embeds new invariants and calls the
   reducers over HTTP, retrying until each row is in. If SpacetimeDB is down, nothing is
   lost and the audit doesn't slow down.
4. **`invariants.db` is the record; SpacetimeDB is a live copy.** The leaderboard checker
   (`scripts/check_leaderboard.py`, frozen) reads `invariants.db` at the repo root. The
   live database can always be rebuilt from it with `python -m harden.store sync`. Note
   that beat 3 still needs the Claude API, so if the network dies on stage, beat 2 still
   works from the local server and beat 3 falls back to the recorded backup.
5. **Embeddings are computed once, in the pusher.** sentence-transformers
   `all-MiniLM-L6-v2` (384 floats, L2-normalized, CPU, no API key), loaded once. Vectors
   live in a private table only module code reads, so dashboard clients never download
   them. SpacetimeDB has no vector index (issue #5376 is open), so similarity is a
   brute-force dot product, which is fine at our scale: the harness rebuilt 300
   invariants in about 0.6 s.
6. **Rules are exploit classes in v1.** One rule per `exploit_class`, with
   similarity edges showing the finer structure inside and across classes. Splitting a
   class into several rules by similarity is a stretch goal.
7. **Run locally.** `spacetime start` on Varun's laptop is the integration server and the
   demo server. Maincloud is cut unless we need a public URL; nothing in the prize rules
   requires it.

## Who owns what

| Piece | Owner | Files |
| --- | --- | --- |
| Shared module files: `schema.ts`, `index.ts`, `package.json`, `tsconfig.json`, `vitest.config.ts`, repo-root `spacetime.json`, generated `dashboard/src/module_bindings/` | Rishab | |
| Core tables and reducers (built in M0a; signatures are the contract) | Rishab | `spacetimedb/src/core_tables.ts`, `core.ts`, `taxonomy.ts` |
| Python pusher: HTTP client, embeddings, `push`, `sync`, `seed`, `replay`, `reset-demo`, `doctor` | Rishab | `harden/store/` |
| Python audit side: mirror writes from audit workers, extraction (Claude), `reconcile`, retrieval | Varun | `harden/store/` |
| Graph tables and graph reducers | Rishab | `spacetimedb/src/graph_tables.ts`, `graph.ts` |
| `buildGraph(rows) → {nodes, edges}` and its tests and fixture | Rishab | `dashboard/src/graph/` |
| Rendering the graph, live updates, leaderboard view | Anirudh | `dashboard/` (everything else) |
| Transfer test for beat 3 | Varun | |

Graph reducers read core tables but never write them, and core code never calls graph
code. `schema.ts` already spreads `graphTables` from `graph_tables.ts`, and `index.ts`
already re-exports `graph.ts`. Varun's audit code and Rishab's pusher meet only at the
SQLite mirror: audit workers write rows, the pusher reads them.

## Data flow

```
audit workers (Python)                     invariants.db  (repo root, checker reads it)
  judge confirms exploit ──► exploits row ─────────┐
  Claude extracts invariant ► invariants row ──────┤  pushed_at = NULL means pending
                                                   ▼
                       harden.store push --watch  (one process, MiniLM loaded once)
                         record_environment / record_exploit / record_invariant
                         then graph_on_invariant(invariant_id)            HTTP /call
                                                   ▼
                       SpacetimeDB "loophole" (TypeScript module)
                         core.ts reducers  ──writes──► core tables
                         graph.ts reducers ──reads core, writes──► graph tables
                                                   ▼  live subscription
                       dashboard: useTable(...) ─► buildGraph(rows) ─► render

judge's game (beat 3)
  compile ─► record_environment('game/<slug>') ─► retrieve rules ─► fixer pre-hardens
  ─► record_rule_application(run_id, invariant_id, 'game/<slug>', outcome, detail)
  ─► hacker runs; anything new goes through the same exploit/invariant path
```

## Servers

- **Integration and demo server: Varun's laptop** (where the audit runs). It runs
  `spacetime start`. Only `main` is published there, only from that laptop (its local
  identity owns the database), and only with `scripts/republish.sh` (Rishab writes it),
  which republishes, then runs `seed` and `sync`. The dashboard
  reads its host from `VITE_SPACETIMEDB_HOST`. If venue Wi-Fi blocks laptop-to-laptop
  traffic, use a tunnel or a Maincloud dev database for integration only.
- **Everyone else develops against vitest and their own `spacetime start`.** Publishing a
  module replaces the whole module with the publisher's copy, so two people publishing
  from different branches to one database overwrite each other.
- **Freeze graph table columns before real data arrives (target Sat 11:00).** After that,
  only add trailing columns with defaults.

## Module layout

```
spacetime.json              repo root: {"database": "loophole", "module-path": "./spacetimedb",
                            "server": "local", "generate": [{"language": "typescript",
                            "out-dir": "./dashboard/src/module_bindings"}]}
spacetimedb/
  package.json, tsconfig.json, vitest.config.ts       (contents below)
  src/
    index.ts        export { default } from './schema'; export * from './core'; export * from './graph';
    schema.ts       const spacetimedb = schema({ ...coreTables, ...graphTables }); export default spacetimedb;
                    export type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;
    core_tables.ts  Rishab  (tables; not re-exported)
    core.ts         Rishab  (reducers ONLY)
    taxonomy.ts     Rishab  (EXPLOIT_CLASSES; not re-exported)
    graph_tables.ts Rishab  (tables; not re-exported)
    graph.ts        Rishab  (reducers ONLY; helpers stay unexported in the file)
    *.test.ts       vitest + spacetimedb/server/test-utils
```

**The one rule that breaks everything if ignored:** every export that reaches `index.ts`
must be a reducer (or lifecycle hook, view or procedure). Re-exporting a plain function or
a constant makes the module fail to load with `TypeError: exporting something that is not
a spacetime export`, both in vitest and on `spacetime publish`. So `core.ts` and `graph.ts`
export only reducers, and helpers live unexported or in files `index.ts` doesn't re-export.
Splitting the module across files this way, with `export *`, was confirmed in the 2.13.0
harness.

Helpers that touch the database take a typed context, `import { type Ctx } from
'./schema'`. Untyped parameters fail `tsc --noEmit`, which `spacetime publish` runs before
it bundles, and it type-checks test files too.

Naming: table names are explicit snake_case, column keys are snake_case, and reducers are
exported as snake_case consts, so Python, SQL and the source use identical names. The
generated TypeScript client shows columns in camelCase (`env_id` → `envId`).

### Module package files

```json
// spacetimedb/package.json  (Node 22+)
{
  "name": "loophole-module",
  "private": true,
  "type": "module",
  "scripts": { "test": "vitest run" },
  "dependencies": { "spacetimedb": "2.13.0" },
  "devDependencies": { "typescript": "~5.9.3", "vitest": "^3.2.4" }
}
```

```json
// spacetimedb/tsconfig.json  (from templates/basic-ts)
{
  "compilerOptions": {
    "strict": true, "skipLibCheck": true, "moduleResolution": "bundler",
    "target": "ESNext", "lib": ["ES2021", "dom"], "module": "ESNext",
    "isolatedModules": true, "noEmit": true
  },
  "include": ["src/**/*"]
}
```

```ts
// spacetimedb/vitest.config.ts
import { defineConfig, type Plugin } from 'vitest/config';
import { spacetimedbModuleTestPlugin } from 'spacetimedb/server/test-utils/vitest';

export default defineConfig({
  plugins: [spacetimedbModuleTestPlugin() as unknown as Plugin],
  test: { environment: 'node' },
});
```

Don't let npm pick TypeScript 7 or vitest 5: the template tsconfig options were removed
in TypeScript 7.

Harness notes: tests do `import spacetimedb, * as mod from './index'` and
`createModuleTestHarness(spacetimedb, mod)`, then `test.withReducerTx(auth, ctx =>
mod.record_exploit(ctx, {...}))`. The harness does not run `init`. It calls reducers as
plain functions, so it checks neither argument types nor HTTP order. `console.log` prints
nothing. f32 values read back rounded (compare with `toBeCloseTo`). Build one harness per
test.

## Core tables (Rishab; built in M0a)

```ts
// spacetimedb/src/core_tables.ts
import { table, t } from 'spacetimedb/server';

export const environment = table({ name: 'environment', public: true }, {
  env_id: t.string().primaryKey(),        // leaderboard env_id ("owner/name"), "game/<slug>" or "seed/<name>"
  source: t.string(),                     // 'hub' | 'game' | 'seed'
  title: t.string(),
  status: t.string(),                     // hub: queued|running|patched|robust|failed_to_run
                                          // game: compiling|pre_hardening|hardening|training|done
  updated_at: t.timestamp(),
});

export const exploit = table({ name: 'exploit', public: true }, {
  invariant_id: t.string().primaryKey(),  // `${env_id}#${exploit_id}`, shared with invariant
  env_id: t.string().index('btree'),
  exploit_id: t.string(),                 // same id as results/leaderboard.json
  exploit_class: t.string(),              // chosen once, here (taxonomy below)
  iteration: t.u32(),                     // 1..5
  summary: t.string(),                    // one line for the dashboard
  sample_completion: t.string(),          // the hack itself, truncated to 2000 chars
  reward_original: t.f32(),               // reward the hack earned before the patch
  reward_patched: t.option(t.f32()),      // set by mark_exploit_patched
  status: t.string(),                     // 'confirmed' | 'patched'
  evidence_path: t.string(),              // repo-relative replay file
  confirmed_at: t.timestamp(),
});

export const invariant = table({ name: 'invariant', public: true }, {
  invariant_id: t.string().primaryKey(),
  env_id: t.string().index('btree'),
  exploit_id: t.string(),
  exploit_class: t.string().index('btree'),  // copied from the exploit row
  title: t.string(),                      // <= 80 chars, node label
  mechanism: t.string(),                  // how the hack works
  root_cause: t.string(),                 // why the reward allowed it
  preconditions: t.string(),              // when the rule applies to another environment
  defense_pattern: t.string(),            // how to block it
  evidence_path: t.string(),
  created_at: t.timestamp(),              // kept on re-record; defines graph order
});

// Private: only module code reads vectors.
export const invariant_embedding = table({ name: 'invariant_embedding' }, {
  invariant_id: t.string().primaryKey(),
  model: t.string(),                      // 'all-MiniLM-L6-v2', or '' if none
  vector: t.array(t.f32()),               // 384 floats L2-normalized, or empty
});

export const rule_application = table({ name: 'rule_application', public: true }, {
  application_key: t.string().primaryKey(),  // `${run_id}:${invariant_id}->${target_env_id}`, so retries upsert
  run_id: t.string().index('btree'),      // one transfer-test attempt; a new attempt gets a new run_id
  invariant_id: t.string().index('btree'),
  target_env_id: t.string().index('btree'),
  outcome: t.string(),                    // 'pre_hardened' | 'blocked' | 'not_blocked' | 'not_applicable'
  detail: t.string(),                     // versioned JSON, {"v": 1, ...}; see Transfer test
  created_at: t.timestamp(),              // kept on retry
});

export const coreTables = { environment, exploit, invariant, invariant_embedding, rule_application };
```

Strings are used instead of SpacetimeDB enums so Python sends plain JSON strings; the
reducers validate the allowed values. The dashboard's leaderboard numbers (ASR, benign
pass rate, cost) come from `results/leaderboard.json`, not from SpacetimeDB.

### Exploit classes

`exploit_class` is chosen **once**, by the judge or engine when an exploit is confirmed.
The same string goes into `leaderboard.json`, `exploit` and `invariant`; extraction never
re-picks it. The list lives in `harden/store/exploit_classes.json`, with a copy in
`spacetimedb/src/taxonomy.ts` that must be kept in sync. The hacker, judge and extraction
prompts all use it. Add a value there before using it.

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

### Core reducers (Rishab; built in M0a)

The pusher calls these over HTTP with a **positional JSON array** in exactly this order.
Timestamps come from `ctx.timestamp`; Python never sends them. Every write is an
idempotent upsert, so the pusher can retry any call. That matters because since 2.13 a
confirmed call can return 504, or 500 with "outcome unknown".

| Reducer | Arguments, in order | Effect |
| --- | --- | --- |
| `record_environment` | env_id: string, source: string, title: string, status: string | Upsert `environment` |
| `record_exploit` | env_id: string, exploit_id: string, exploit_class: string, iteration: u32, summary: string, sample_completion: string, reward_original: f32, evidence_path: string | Upsert `exploit`. A new row starts with status 'confirmed'; an existing row keeps status, reward_patched and confirmed_at |
| `mark_exploit_patched` | env_id: string, exploit_id: string, reward_patched: f32 | Set reward_patched (a plain number) and status 'patched' |
| `record_invariant` | env_id: string, exploit_id: string, title: string, mechanism: string, root_cause: string, preconditions: string, defense_pattern: string, evidence_path: string, embedding_model: string, embedding: f32[] | Upsert `invariant` (exploit_class copied from the exploit row, created_at kept on re-record) and `invariant_embedding` |
| `record_rule_application` | run_id: string, invariant_id: string, target_env_id: string, outcome: string, detail: string | Upsert keyed by `${run_id}:${invariant_id}->${target_env_id}`. Retries of one attempt update one row (latest outcome wins, created_at kept); a new attempt uses a new run_id and gets its own row. `detail` must be a JSON object with `"v": 1`; the invariant and the target environment must exist |
| `clear_environment` | env_id: string | Delete this env's exploit, invariant and invariant_embedding rows, plus rule_application rows whose invariant belongs to it or whose target is it. Keep the environment row |

Validation (throw `SenderError`, which rolls back the call): the environment row exists;
for `record_invariant`, the exploit row exists. `exploit_class` is in the taxonomy,
`iteration` is 1..5, and `outcome` and `source` are allowed values. mechanism, root_cause,
preconditions and defense_pattern are each at least 10 characters (the checker's rule).
The embedding is empty or has 384 finite values with |‖v‖ − 1| < 1e-3. Reducers truncate
`title` to 80 and `sample_completion` to 2000 characters instead of rejecting.

Python runs the same validation **before** writing SQLite, so the mirror never holds a row
the reducer would reject.

Auth: none. The server binds to localhost on stage (see bring-up). Add a writer allowlist
only if we ever deploy to Maincloud.

## Graph (Rishab)

### Graph reducers

Called by the pusher after core writes, and from the CLI for tuning. Every one starts by
ensuring the `graph_config` row exists (insert defaults if missing). Don't rely on
`init`: it runs only on the first publish and after a wipe, never on a normal republish,
so it would never run when the graph tables first arrive.

| Reducer | Arguments | Effect |
| --- | --- | --- |
| `graph_on_invariant` | invariant_id: string | Recompute this invariant's similarity edges, then refresh rules |
| `rebuild_graph` | none (HTTP body `[]`) | Clear `similarity_edge`; replay `graph_on_invariant` over all invariants in (created_at, invariant_id) order; refresh rules |
| `set_graph_config` | edge_threshold: f32, max_edges_per_node: u32 | Update the config, then rebuild |
| `set_rule_title` | rule_id: string, title: string | Upsert `rule_title`, which rebuilds never touch |

`graph_on_invariant(X)`:

1. Delete `similarity_edge` rows where X is `a_id` or `b_id` (delete through both indexes).
2. If X no longer exists (it was cleared), stop after refreshing rules.
3. Score X against every invariant **earlier** than X in (created_at, invariant_id) order.
   Vectors are normalized, so the score is a dot product. Skip empty vectors.
4. Keep the top `max_edges_per_node` scores that are at least `edge_threshold`. Upsert each
   with `edge_id` set to `a|b`, where `a < b`.
5. Refresh rules: recompute every `rule` row from the invariants. That's cheap with about
   ten classes, and it handles an invariant moving class or disappearing.

Comparing only against earlier invariants means a rebuild reproduces exactly the graph that
live arrival built. Because every key is deterministic, a rebuild that produces identical
rows is invisible to subscribers: SpacetimeDB skips a delete-then-identical-insert in the
same transaction. Never use autoInc ids or `updated_at` columns in graph tables, or every
rebuild redraws the whole dashboard. If an invariant's text is edited, call `rebuild_graph`
so later invariants' edges to it get refreshed (`sync` always ends with one).

Reducers must be deterministic: no `Math.random`, no network, no module-level state.

### Graph tables (Rishab)

```ts
// spacetimedb/src/graph_tables.ts
import { table, t } from 'spacetimedb/server';

export const graph_config = table({ name: 'graph_config', public: true }, {
  id: t.u32().primaryKey(),               // always 0
  edge_threshold: t.f32(),                // start 0.45: on the seed vectors same-class pairs average 0.49,
                                          // cross-class 0.34; 0.45 gives 15 of 66 edges, 0.55 only 4
  max_edges_per_node: t.u32(),            // start 5 (unbounded gave 11,100 edges at 300 nodes)
});

export const similarity_edge = table({ name: 'similarity_edge', public: true }, {
  edge_id: t.string().primaryKey(),       // `${a_id}|${b_id}`, a_id < b_id
  a_id: t.string().index('btree'),
  b_id: t.string().index('btree'),
  score: t.f32(),
});

export const rule = table({ name: 'rule', public: true }, {
  rule_id: t.string().primaryKey(),       // v1: the exploit_class
  title: t.string(),                      // rule_title override, else the class's display name
  defense_pattern: t.string(),            // from the earliest member by (created_at, invariant_id)
  member_count: t.u32(),
  env_count: t.u32(),                     // distinct env_id among members
});

export const rule_title = table({ name: 'rule_title', public: true }, {
  rule_id: t.string().primaryKey(),
  title: t.string(),
});

export const graphTables = { graph_config, similarity_edge, rule, rule_title };
```

A rule with no members is deleted. Rule membership is `invariant.exploit_class ==
rule.rule_id`, so v1 needs no membership table. If we later split classes by similarity,
add a `rule_member` table then; adding tables later is safe.

### What the dashboard draws

`buildGraph` is a pure function from subscribed rows (generated client types: camelCase
fields, `bigint` for u64, `T | undefined` for options) to nodes and edges. Rishab tests it
with plain vitest on fixture rows; Anirudh only renders its output. Rishab also commits
`dashboard/src/graph/fixture.graph.json` early, so Anirudh can build the view before the
module exists.

```ts
type GraphRows = {
  environments: Environment[];
  exploits: Exploit[];
  invariants: Invariant[];
  rules: Rule[];
  similarityEdges: SimilarityEdge[];
  ruleApplications: RuleApplication[];
};

function buildGraph(rows: GraphRows, opts?: { hideSeed?: boolean }): { nodes: GraphNode[]; edges: GraphEdge[] };

type GraphNode =
  | { id: `env:${string}`;  kind: 'environment'; label: string; source: string; status: string }
  | { id: `inv:${string}`;  kind: 'invariant';   label: string; exploitClass: string; envId: string; pending: boolean }
  | { id: `rule:${string}`; kind: 'rule';        label: string; memberCount: number; envCount: number };

type GraphEdge = {
  id: string;                // deterministic, see below
  kind: 'found_in' | 'instance_of' | 'similar_to' | 'applied_to';
  source: string;            // node id
  target: string;            // node id
  weight?: number;           // similar_to: score
  outcome?: string;          // applied_to: rule_application.outcome
};
```

| Edge | Id | From rows | Meaning |
| --- | --- | --- | --- |
| `found_in` | `found_in:<invariant_id>` | `invariant.envId` | invariant → the environment it was learned on |
| `instance_of` | `instance_of:<invariant_id>` | `invariant.exploitClass` | invariant → its rule |
| `similar_to` | `similar_to:<a>\|<b>` | `similarity_edge` | invariant ↔ invariant, weight = score |
| `applied_to` | `applied_to:<invariant_id>-><target_env_id>` | `rule_application` | the invariant's rule → target environment, from the latest run (max created_at) for that pair, so new attempts update the edge instead of adding one (`blocked` is the beat 3 money shot) |

- An `exploit` row with no `invariant` row yet is drawn as an invariant node with
  `pending: true`. It appears the moment the judge confirms the hack, and fills in when
  extraction lands.
- Drop any edge whose endpoint node hasn't arrived: tables arrive independently.
- `hideSeed` drops environments with `source == 'seed'` and everything attached to them.

## Python side (pusher and CLI: Rishab; audit side, extraction, reconcile, retrieval: Varun)

`harden/store/`, configured from `.env`: `SPACETIME_HOST` (default `http://127.0.0.1:3000`),
`SPACETIME_DB` (default `loophole`). The token is minted with `POST /v1/identity` on first
use and saved to `.spacetime_token` (gitignored). Tokens work only on the server that
issued them, so the client re-mints on a 401.

### Mirror (`invariants.db`, repo root)

```sql
CREATE TABLE environments (env_id TEXT PRIMARY KEY, source TEXT, title TEXT, status TEXT,
  updated_at TEXT, pushed_at TEXT, push_error TEXT);
CREATE TABLE exploits (env_id TEXT, exploit_id TEXT, exploit_class TEXT, iteration INTEGER,
  summary TEXT, sample_completion TEXT, reward_original REAL, reward_patched REAL,
  status TEXT, evidence_path TEXT, confirmed_at TEXT, pushed_at TEXT, push_error TEXT,
  PRIMARY KEY (env_id, exploit_id));
CREATE TABLE invariants (env_id TEXT NOT NULL, exploit_id TEXT NOT NULL,
  mechanism TEXT, root_cause TEXT, preconditions TEXT, defense_pattern TEXT,
  evidence_path TEXT,                       -- the checker reads the 7 columns above
  exploit_class TEXT, title TEXT, embedding_model TEXT, embedding BLOB,
  created_at TEXT, pushed_at TEXT, push_error TEXT,
  PRIMARY KEY (env_id, exploit_id));
CREATE TABLE rule_applications (run_id TEXT, invariant_id TEXT, target_env_id TEXT,
  outcome TEXT, detail TEXT,              -- versioned JSON, the same string pushed to SpacetimeDB
  created_at TEXT, pushed_at TEXT, push_error TEXT,
  PRIMARY KEY (run_id, invariant_id, target_env_id));
```

- Writers use single-statement `INSERT ... ON CONFLICT DO UPDATE` (which resets
  `pushed_at` to NULL), `PRAGMA busy_timeout=10000`, and one connection per thread.
  Leave the default journal mode. **Don't enable WAL**: a commit of the file while a WAL
  writer is open captures a database with rows missing (tested). Add
  `invariants.db-journal` to `.gitignore`.
- `env_id` is always the exact `leaderboard.json` string. For leaderboard rows,
  `evidence_path` is `posixpath.join(entry["evidence_dir"], exploit["replay"])`, that
  exploit's own replay file. The checker rejects anything else.
- When the audit starts (or restarts) an environment, it calls `clear_environment(env_id)`
  on **both** stores, so a re-run never inherits stale exploit ids.

### API

```python
record_environment(env_id, *, source, title, status)
record_exploit(env_id, exploit_id, *, exploit_class, iteration, summary,
               sample_completion, reward_original, evidence_path)
mark_exploit_patched(env_id, exploit_id, *, reward_patched)
extract_invariant(evidence, *, exploit_class) -> Invariant    # Claude, JSON schema; class is an input
record_invariant(inv: Invariant)                              # mirror only; the pusher embeds and pushes
record_rule_application(run_id, invariant_id, target_env_id, outcome, detail: dict)  # adds "v": 1
retrieve(env_source, task, k=5) -> list[Match]                # see Retrieval
clear_environment(env_id)                                     # both stores
```

### CLI (`python -m harden.store ...`)

| Command | What it does |
| --- | --- |
| `push --watch` | The only process that talks to SpacetimeDB. Pushes pending rows in order (environments, exploits, invariants, applications). It embeds invariants that lack a vector, calls `graph_on_invariant` after each invariant, retries with backoff, and sets `pushed_at` or `push_error` |
| `sync` | Mark everything pending, push it all once, then `rebuild_graph`. Recovers a wiped or fresh server |
| `seed` | Push `fixtures/invariants.sample.json` through the same reducers. SpacetimeDB only, never the mirror |
| `reconcile` | Make the mirror match `results/leaderboard.json` before any checker run or commit. Patched entries: exactly one complete `invariants` row per listed exploit (extract missing ones, up to 3 retries), stale rows deleted, evidence_path set to that exploit's replay. Robust entries: rows deleted. failed_to_run entries and non-leaderboard envs: untouched |
| `replay --delay 1.0` | Clear the hub envs from SpacetimeDB, then push the mirror's hub rows in `confirmed_at` order, so the graph builds up on screen (beat 2 and the Devpost video, labelled as a replay of Saturday's audit) |
| `reset-demo` | `clear_environment` for every `game/*` env in both stores, before going on stage |
| `doctor` | Token valid; row counts match `leaderboard.json`; pending and errored pushes; graph_config present |

Before committing results: `reconcile`, then `python scripts/check_leaderboard.py`, then
commit `invariants.db`. M0 also adds `tests/test_store_checker.py`, which builds a temp repo
and calls `check_leaderboard.check_invariants` for the patched, robust, re-run and
missing-row cases.

### Retrieval

Implementation update: Rishab has added opt-in graph retrieval and loop adapters at the
user's request. See [GRAPH_RETRIEVAL.md](GRAPH_RETRIEVAL.md) for bounded top-k selection,
target/source isolation, replay contracts, and integration tests. Varun's loop can call
`run_knowledge_transfer` and persist its application rows through the audit writer.
The original prompt-only design below is retained as background; the implementation
uses graph-neighbour ranking before the fixer prompt. Retrieval requires an explicit
`target_env_id`. The writer, pusher, and target execution remain separate integrations.

With fewer than about 100 invariants, retrieval is one fixer prompt. It contains every
non-seed invariant's title, preconditions and defense_pattern plus the new environment's
reward source, and the fixer returns the invariant_ids it applied. Embedding similarity
is only a tiebreak, from the already-loaded MiniLM. Budget: retrieval plus pre-hardening
in 15 s or less after compiling. Retrieval output never includes `sample_completion` or
evidence paths: the checker rejects patches that embed exploit text or name evidence
files, and defenses must be written into the patch as code, never looked up from
`invariants.db` at runtime.

## Transfer test (beat 3, Varun)

The target is **never** a leaderboard environment, because pre-hardening one would make the
engine's view disagree with the checker, which scores every attack against the original
reward. The target is the judge's game (`game/<slug>`) or a held-out hub environment that
isn't in `leaderboard.json`.

1. Compile, then call `record_environment('game/<slug>', 'game', title, 'compiling')`. Mint
   a fresh `run_id` for this attempt (for example `t-<unix seconds>`); every
   application row in this attempt uses it, and retries reuse it.
2. Retrieve the applicable invariants. The fixer writes the pre-hardened reward, and each
   applied invariant gets `record_rule_application(run_id, inv, env, 'pre_hardened', ...)`.
3. For each applied invariant, ask the hacker once to "apply this mechanism to this
   environment". Score that one completion under the unhardened and pre-hardened rewards
   (pass = at least 0.8 × the reference completion's reward):
   - `blocked`: passes unhardened, fails pre-hardened
   - `not_blocked`: passes both
   - `not_applicable`: fails both

   `detail` = JSON `{"v": 1, "score_unhardened": x, "score_pre_hardened": y,
   "completion": "<first 200 chars>"}`. Bump `v` and update the reducer whenever the shape
   changes; readers switch on `v`.
4. Anything new the hacker finds goes through `record_exploit` / `record_invariant`, so new
   nodes appear live and attach to their rule.

Pair to rehearse: a `substring-match` or `multi-answer` invariant learned on a hub env,
applied to a number-guessing game compiled with the build plan's loose "answer anywhere"
parser. The three suggested game types shown on screen should match exploit classes
already in the store.

## Seed data (unblocks Rishab and Anirudh now)

`fixtures/invariants.sample.json` (in the repo) holds invented invariants: 12 across 6
`seed/...` environments, with several sharing a class so rules and edges actually form,
plus one transfer target and two applications. Its shape is
`{version, environments: [record_environment args], entries: [{env_id, exploit:
{record_exploit args}, invariant: {record_invariant text fields}, embedding_model,
embedding}], applications: [record_rule_application args]}`. The embeddings are real
`all-MiniLM-L6-v2` vectors, precomputed with `scripts/embed_fixture.py`, so Rishab's tests
and threshold tuning never need Python or torch. `spacetimedb/src/core.test.ts` already
loads the whole fixture through the reducers in that order. The `seed` command does the
same over HTTP, then calls `graph_on_invariant`. Seed rows are excluded from retrieval on
stage, so the judge's game is pre-hardened only by rules learned from real runs. After any
wipe, run `seed`, then `sync`.

## Milestones

It is Sat 03:45 as this is written. Checkpoint 1 is at 12:00, Checkpoint 2 at 18:00, the
feature freeze at midnight, and submission Sun 09:00.

| | What | Who | Due |
| --- | --- | --- | --- |
| M0a | **Done.** Skeleton pushed: shared files, `core_tables.ts`, `core.ts`, `taxonomy.ts`, empty `graph_tables.ts`/`graph.ts` that compile, the fixture with vectors, 16 harness tests | Varun | Sat 05:00 |
| M0 | First real publish passes the checklist below; `harden.store` client, pusher and checker test | Rishab | 09:00 |
| M2a | Audit writes mirror rows; `reconcile` + checker pass on 3 envs | Varun | 12:00 (Checkpoint 1) |
| M1 | Graph tables and reducers, `buildGraph`, `fixture.graph.json`, vitest tests on seed vectors | Rishab (starts now) | 15:00 |
| M2b + M3 | Pusher live during the audit; dashboard draws the live graph from the integration server | Rishab, Anirudh | 18:00 (Checkpoint 2) |
| M4 | Transfer test working on the rehearsal pair | Varun | 22:00 |
| Freeze | `reconcile`, commit the mirror, `reset-demo`, offline rehearsal, record the `replay` video | all | Sun 00:00–08:00 |

If M1 or M3 slips past 18:00, show the invariant list from `useTable(tables.invariant)` and
move on. That's the build plan's first cut.

### M0 checklist (needs a real server)

Already confirmed in the 2.13.0 harness: the split layout loads; `export *` registers
reducers; positional parameters follow declaration order; `t.option(t.f32())`,
`t.array(t.f32())` and u64 behave as described; `SenderError` rolls back.

- [ ] `spacetime publish` loads the module with no "not a spacetime export" error.
- [ ] Python's positional JSON calls work for every reducer, including `f32[]` embeddings,
      a `u32` iteration (out of range rejected) and the no-argument `rebuild_graph` (body
      `[]`).
- [ ] A Python write shows up in a React `useTable` subscription, with event tag
      `'Transaction'`.
- [ ] `push --watch` recovers after `spacetime start` is killed and restarted.

## Local setup

Each person installs the CLI once (the official installer) and Node 22+:

```bash
curl -sSf https://install.spacetimedb.com | sh
```

```bash
spacetime start                 # terminal 1: local server on :3000
cd spacetimedb && npm install && npm test
cd .. && spacetime publish      # repo-root spacetime.json supplies database, module path and server
spacetime generate              # writes dashboard/src/module_bindings
spacetime sql loophole "SELECT * FROM invariant"
spacetime logs -f loophole
```

The first publish asks whether to log in to spacetimedb.com. Answer **n** for local work,
so the local server issues your identity and you own the database.

Dashboard wiring (2.x):

```tsx
// dashboard/src/main.tsx
import { SpacetimeDBProvider } from 'spacetimedb/react';
import { DbConnection } from './module_bindings';

const HOST = import.meta.env.VITE_SPACETIMEDB_HOST ?? 'ws://localhost:3000';
const connectionBuilder = DbConnection.builder().withUri(HOST).withDatabaseName('loophole');
// render: <SpacetimeDBProvider connectionBuilder={connectionBuilder}><App /></SpacetimeDBProvider>

// in components:
import { useTable } from 'spacetimedb/react';
import { tables } from './module_bindings';
const [invariants, ready] = useTable(tables.invariant);
```

The dashboard only reads, so it connects anonymously, with no token persistence.

### Demo laptop bring-up (rehearse with Wi-Fi off)

1. `spacetime start --listen-addr 127.0.0.1:3000`. Never use `--in-memory` and never run
   `spacetime server clear`. Data on disk survives restarts.
2. Publish with a local-server identity, not a spacetimedb.com login: an offline local
   publish fails if the CLI holds a cloud token.
3. `seed`, then `sync` from the committed mirror, then `doctor`.
4. Download `all-MiniLM-L6-v2` ahead of time, then run with `HF_HUB_OFFLINE=1`.
5. Kill and restart `spacetime start`, and confirm the dashboard and pusher recover.

## Gotchas (SpacetimeDB 2.x)

- **The CLI's default server is Maincloud.** The repo-root `spacetime.json` sets
  `"server": "local"`, but the CLI only finds the file from the current directory or a
  parent. Outside the repo, pass `-s local`.
- **Schema changes.** A republish can add tables, indexes and reducers, and can add a
  column only at the end of a table with `.default(...)`. Anything else needs
  `spacetime publish --delete-data -y`, which wipes every table (recover with `seed`, then
  `sync`). Flag values need `=`, as in `--delete-data=on-conflict`.
- **Exports.** Only reducers, lifecycle hooks, views and procedures may reach `index.ts`
  (see Module layout).
- **Tables are private by default**, missing from generated bindings and invisible to
  subscribers. Everything the dashboard reads is `public: true`.
- **Only primary keys have `.update()`.** Find by primary key, then update.
- **SQL is limited.** No ORDER BY, GROUP BY, DISTINCT or LIKE; one statement per HTTP
  request; subscriptions return full rows of one table. Sort in code.
- **HTTP.** `Content-Type` must be exactly `application/json` (requests' `json=` is
  right). No-argument reducers still need the body `[]`. A call without a token gets a
  fresh anonymous identity. Every HTTP call also runs `client_connected` and
  `client_disconnected`, so don't define those.
- **TS SDK.** u64 is `bigint`, options are `T | undefined`, columns are camelCase. In 2.x,
  callbacks for other clients' reducer calls are gone, so drive the UI from
  `useTable`/`onInsert`.
- **Stale examples.** 1.x code uses `withModuleName`, `@clockworklabs/spacetimedb-sdk` and
  `schema(t1, t2)`. In 2.x these are `withDatabaseName`, `spacetimedb`, and
  `schema({ t1, t2 })` as the default export.

## SpacetimeDB prize

$2,048 / $1,024 / $512 for the "most impressive use of Spacetime". It's on the Hive live
site but not yet on Devpost, so ask at the SpacetimeDB workshop (Sat 4–5 PM, Theater) how
to enter. The only stated bar is that SpacetimeDB is the core real-time backend. What we
show: the graph computed by reducers, the dashboard updating live as hacks are confirmed
(pending node, then the invariant, then its edges), and a stored rule blocking the same
exploit on the judge's game. Devpost wants a video for sponsors who judge asynchronously,
so record the `replay` run. The deadline is Sun Oct 25, 9:00 AM PDT.

## Cut or stretch

- Splitting a class into several rules by similarity (needs `rule_member`): stretch.
- Moving retrieval into a SpacetimeDB procedure: stretch.
- Maincloud, the writer allowlist and a public URL: cut unless integration needs it.
- An event table for "exploit confirmed" toasts: stretch; pending nodes already show it.

## Open questions

1. **Ownership (resolved Sat 04:00).** Rishab owns the whole `spacetimedb/` module and the
   pusher; Varun owns the audit side. See the handoff section at the top.
2. **Embedding model.** If PyTorch is too heavy for the pusher, any local model works. The
   contract is "384 normalized floats plus a model name, or empty"; a different dimension
   means changing the validation.
3. **Prize entry.** Who goes to the 4 PM workshop?

## Sources

SpacetimeDB 2.13.0 docs and source (clockworklabs/SpacetimeDB at 155f305, Oct 23, 2026):
tables, column types, indexes, reducers, lifecycle, automatic migrations, transactions,
HTTP API (`/v1/identity`, `/call`, `/sql`), SATS-JSON, SQL reference, TypeScript SDK and
React integration, unit testing, `spacetime.json`, the module export check in
`crates/bindings-typescript/src/server/schema.ts`, and the `basic-ts` and `chat-react-ts`
templates. Cal Hacks 13.0: hive.hackberkeley.org (prizes, schedule),
cal-hacks-13-0.devpost.com, spacetimedb.com/blog/spacetime-at-calhacks.

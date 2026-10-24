# Graph and invariant-store contract

Implemented against the reviewed [invariant store plan](INVARIANT_STORE.md) and
Varun's core module skeleton at `45a6445`. That plan defines the core schema;
this document describes the implemented graph boundary.

## Ownership and persistence

Varun owns audit-side SQLite writes, extraction, and hardener integration. Per the latest
handoff, Rishab owns the SpacetimeDB module, embedding/pusher infrastructure, and
`spacetimedb/src/graph_tables.ts`, `spacetimedb/src/graph.ts`, and the pure dashboard
projection in `dashboard/src/graph/buildGraph.ts`. Graph reducers read core records
without modifying them. SQLite is the durable source; SpacetimeDB supplies live rows.

The cross-store invariant identity is `env_id + "#" + exploit_id`. Embeddings use the
same invariant ID. Application attempts use `application_key`, derived by the core
writer from run, invariant, and target identities. Retrying an attempt upserts it;
a new run retains a separate attempt. Preserve the versioned JSON `detail` and the
same logical application record in SQLite. Evidence paths refer to provenance, not
executable patches.

## Pusher protocol

1. Persist core records in SQLite, then mirror them through core reducers.
2. After an invariant and embedding are recorded, invoke
   `graph_on_invariant(invariant_id)` independently. Core and graph writes are separate
   transactions. Retry the graph notification if it fails.
3. After bulk sync or deletions, invoke `rebuild_graph()`.
4. Mirror application attempts through `record_rule_application`. The dashboard
   projects these rows directly; they require no graph notification.

The dashboard tolerates incomplete subscriptions during this sequence. There is no
synchronous graph hook inside the core reducer. Export only registered reducers from
`graph.ts`, because `index.ts` re-exports them to the SpacetimeDB module loader.

## Graph tables and reducers

| Table | Identity | Meaning |
| --- | --- | --- |
| `graph_config` | `id = 0` | Threshold and earlier-neighbour limit; defaults 0.45 and 5 |
| `similarity_edge` | `${a_id}\|${b_id}` | Canonical undirected pair, with `a_id < b_id`, cosine score |
| `rule` | exploit class | Derived membership counts, earliest member's defense, display title |
| `rule_title` | exploit class | Persistent custom title, surviving deletion/recreation |

There is one rule per exploit class in v1; membership is implicit in each invariant's
`exploit_class`. There is no `rule_member` table.

Reducers: `graph_on_invariant(invariant_id)`, `rebuild_graph()`,
`set_graph_config(edge_threshold, max_edges_per_node)`, and
`set_rule_title(rule_id, title)`. Each initializes missing config. Threshold must be
finite in [0, 1], edge limit a u32 (zero disables edges), and a title 1–80 trimmed
characters for a known exploit class.

Invariants sort by `(created_at, invariant_id)`. Each selects its top k compatible
earlier neighbours meeting the threshold, breaking score ties by invariant ID.
Vectors must have matching model and dimension and finite, nonzero components.
Cosine scores are normalized and rounded to stored f32 precision before comparison.
The limit bounds earlier neighbours, not total undirected degree.

Every notification deterministically recomputes desired graph rows, reconciling
existing IDs. This deliberately replaces the draft's local edge update: changing an
earlier vector can change a later invariant's top-k choices. Recompute ensures
notifications, retries, edits, deletions, and full rebuilds converge. Cost is
O(n² × vector dimension); the suite exercises 300 invariants. Larger deployments
will need measured optimization without changing these semantics.

## Dashboard boundary

`buildGraph(rows, { hideSeed?: boolean })` returns `{ nodes, edges, diagnostics }`.
`GraphRows` takes camelcase generated-client fields in `environments`, `exploits`,
`invariants`, `rules`, `similarityEdges`, and `ruleApplications` arrays. The TypeScript
interfaces in `buildGraph.ts` are the exact consumer contract.

Node IDs are `env:<id>`, `inv:<id>`, and `rule:<class>`. A confirmed exploit appears
as a pending invariant node until its invariant arrives, retaining the same ID.
Edges are:

- `found_in:<invariant>`: invariant → source environment.
- `instance_of:<invariant>`: invariant → class rule.
- `similar_to:<a>|<b>`: canonical invariant pair, with weight.
- `applied_to:<invariant>-><target>`: rule → target, with recorded outcome.

Missing endpoints produce diagnostics and no dangling edges. For each invariant and
target, only the latest attempt by `createdAt` is displayed; equal times use lexical
`applicationKey`. A later invalid outcome is diagnosed, rather than displaying an
older success. Source-environment applications are excluded from transfer edges.
`hideSeed` removes seed environments, their members and attached edges, and rules
with no remaining members; displayed counts reflect visible members.

Outcomes are `pre_hardened`, `blocked`, `not_blocked`, and `not_applicable`.
The graph displays recorded results; it does not independently execute exploits or
certify defenses. A real blocked claim requires target-specific exploit and benign
validation evidence from the hardening system.

## Verification

See [GRAPH_VERIFICATION.md](GRAPH_VERIFICATION.md) for commands, measured coverage,
the dashboard fixture, and remaining integration boundaries.

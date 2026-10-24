# Graph verification and demo handoff

## Reproduce

Use Node 22 or newer from the repository root:

```sh
npm ci --prefix spacetimedb
npm run typecheck --prefix spacetimedb
npm run test:coverage --prefix spacetimedb
```

Verified result: **58 tests passed**, TypeScript passed. Coverage for `graph.ts`,
`graph_tables.ts`, and `buildGraph.ts`: **100% statements/lines/functions, 95.15%
branches**. Core tests also run; these percentages measure the graph-owned files,
not the entire project. HTML report: `spacetimedb/coverage/index.html` (generated,
gitignored). Coverage gates enforce 90% statements/lines/functions and 80% branches.

## What the tests prove

- The actual SpacetimeDB SDK loads the module and registers all core and graph
  reducers with the expected parameters. Tests use its official transactional
  in-process harness rather than an imitation of its table API.
- All 16 existing core tests pass alongside 23 graph reducer tests and 19 dashboard
  projection tests.
- Real seed fixture records flow through core reducers, graph reducers, and the
  dashboard projection. All four edge kinds appear, with no dangling references or
  unexpected diagnostics.
- Repeated and reversed notifications converge to the same rebuild; embedding
  changes update scores and later neighbours; deletions repair rules and edges;
  custom titles persist; invalid config rolls back; graph writes preserve core rows.
- At 300 invariants with five earlier neighbours allowed, exactly 1,485 edges are
  generated and repeat rebuilds remain identical.
- Dashboard tests cover pending nodes, independent subscription arrival, seed hiding,
  duplicate edges, all transfer outcomes, latest-attempt selection, malformed records,
  source-environment exclusion, and input immutability.

## Demonstrable output

`dashboard/src/graph/fixture.graph.json` is a checked-in golden graph generated from
the real seed data through the complete reducer/projection path. The end-to-end test
compares current output with it, so changes cannot silently alter the demo fixture.
The dashboard owner can use its `nodes`, `edges`, and `diagnostics` directly for a
static graph preview before live subscriptions are wired.

To intentionally regenerate after a reviewed contract change:

```sh
UPDATE_GRAPH_FIXTURE=1 npm test --prefix spacetimedb
npm run test:coverage --prefix spacetimedb
```

## Scope and integration boundaries

This verifies the implemented graph/store module and projection against fixture data.
It does not demonstrate a deployed SpacetimeDB server, live browser subscriptions,
SQLite pusher recovery, or actual independent-environment exploit execution. Those
require the other owners' integrations and real target-run evidence. No simulated
transfer outcome should be presented as a measured real exploit result.

The graph is aligned with the reviewed core skeleton on main (`45a6445`). The shared
protocol is in [GRAPH_STORE_CONTRACT.md](GRAPH_STORE_CONTRACT.md).

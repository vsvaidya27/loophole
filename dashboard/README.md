# Live knowledge dashboard

A React + TypeScript dashboard for the live knowledge store, built with Vite. It is
the live companion to the existing `trainer/viz_template.html` replay page.

```sh
npm ci --prefix dashboard
npm run dev --prefix dashboard
# http://127.0.0.1:5173/
```

Node 22.12+ is required by the dashboard's test runner. The module retains its own
separate SDK/test setup. Build and verify with:

```sh
npm run build --prefix dashboard
npm test --prefix dashboard
```

The default connection is `wss://maincloud.spacetimedb.com`, database
`loophole-knowledge-calhacks-2026`. Override with `VITE_SPACETIMEDB_HOST` and
`VITE_SPACETIMEDB_DB` in your shell before starting/building. No writer token belongs in
Vite configuration: frontend environment values are public in the browser bundle.

The app subscribes once to six public tables and updates on insert/update/delete events,
without polling. It labels initial load, connection loss and errors, supports reconnect,
always includes the entire store, and uses the shared `buildGraph` projection.
The dark node canvas shows each environment as a large hub, with its invariant
records as colored satellites. Satellite colors distinguish failure classes. Violet
diamond nodes represent shared rule families; the full graph remains visible when
you focus a node. Source, similarity and tested-transfer links
are distinct; selection highlights evidence without filtering data. Select an invariant for the Failure, Defense, and Transfer inspector tabs: submitted
completion, original and patched rewards, mechanism, preconditions, defense, evidence
path, and recorded transfer outcomes. Missing measurements stay explicitly unavailable. It displays recorded evidence, not an independent certification of it.

The game/training replay link initially shows an honest empty placeholder. Generate the
actual replay from rollout artifacts when they exist:

```sh
python3 -m trainer.viz --rollouts rollouts --out dashboard/public/replay.html \
  --graph-url http://127.0.0.1:5173/
```

That generated file replaces the placeholder locally. Do not present an empty replay or
the graph calibration as trained-policy performance. The replay template also gains a
link back to the live graph; its existing rendering stays intact.

The production build is static (`dashboard/dist`); deploy those files on any static host
with HTTPS. The service address is already public, but the local dev URL is not a public
frontend deployment. Close the live tab when done to let the hosted database become idle.

## Frontend structure

- `src/main.tsx` mounts the dashboard in React Strict Mode.
- `src/App.tsx` owns record selection and composes the dashboard.
- `src/hooks/useLiveStore.ts` manages the existing SpacetimeDB connection, reconnects,
  page restoration, and cleanup. Displayed records stay visible with a stale label
  until the new subscription arrives.
- `src/components/` contains the React SVG network, evidence inspector, connection
  status, and audit table. Keyed records retain keyboard focus during live updates.
- `src/graph/layoutGraph.ts` and `buildGraph.ts` remain pure layout and projection
  functions. Generated bindings and the six public table subscriptions are unchanged.

The test suite includes subscription and layout tests plus DOM interaction tests for
selection, evidence tabs, live updates, reconnects, and lifecycle cleanup. Test data
is isolated in test files; Live audits always uses the configured live database.

## Showcase dashboard

Choose **Showcase** in the shared navigation, or open `/#showcase/trading`. The three
demos from the upstream `showcase` branch use the same React shell, dark panels,
colors, and responsive layout as Live audits. Switching views keeps the live
subscription and evidence selection intact.

- **Guided demo** is the default: initial task → RL environment visualization →
  reward loophole → revised environment → knowledge graph. Use Next/Back or the
  five stage buttons to present it. Episodes can be played or stepped through.
  The final evidence map explains the selected example; the expandable recorded
  graph uses the existing live subscription and opens nodes in Live audits.
- Trading and computer use include interactive replays with
  play/pause, stepping, speed controls, a scrubber, and a task selector. Compare the
  three policies' strict scores with what the loose reward pays, and inspect raw
  answers or recorded actions. Captured web pages run in sandboxed frames with
  scripts, network access, and form submissions disabled.
  Shop recordings use illustrated product cards and cart quantities/totals derived
  from the captured state; action numbers and recorded verdicts are preserved.
- Voice support includes five selected audit calls, per-turn synthesized audio,
  both judge verdicts, and their prompts. Aggregate rates are from the full audit.
- Every demo includes its original film. Media loads on demand; audio is stored as
  individual MP3 files rather than embedded in the JavaScript bundle.

The trading and computer-use artifacts are **recorded GPU training runs** from
showcase revision `c580715`: base, trained on loose reward, and trained on fixed
reward. Each has 24 held-out tasks. The featured example follows upstream's
contrast ranking (hacked fails while hardened passes, preferring a base failure),
while means include all tasks. Original example numbers are retained.
Computer use has separate strict and loose episodes, so its replay provides an
environment selector and uses the matching pages and action transcript.
Voice uses recorded simulated audit calls with Cartesia voices reading the text;
it demonstrates a revised judge, not a retrained agent. The walkthrough does not
run training, generate environments, or publish knowledge records. The live graph
shows existing audit data separately from the explanatory example map.

The imported source revision, catalog metrics, evidence JSON, and media are checked
in. Refresh them deliberately after fetching a newer showcase branch:

```sh
git fetch upstream showcase
python3 dashboard/scripts/import_showcase.py --ref upstream/showcase
npm test --prefix dashboard
npm run build --prefix dashboard
```

The importer reads Git objects and copies only showcase artifacts, so it does not
replace the dashboard with the older application from that branch. The Showcase
tests cover the guided sequence, reward comparisons, graph inspection, playback
lifecycle, strict/loose episodes, example changes, all three demos, evidence labels,
asset loading failures, video selection, and catalog agreement with source data.

# Live knowledge dashboard

This is the live companion to the existing `trainer/viz_template.html` replay page.
All fetched team branches were checked: that replay page was the only existing visual
UI; `dashboard/` previously contained graph projection and SDK bindings only.

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

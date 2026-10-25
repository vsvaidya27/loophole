# Hosted knowledge graph

The knowledge graph runs on SpacetimeDB Maincloud as database `loophole-knowledge-calhacks-2026`. It is served independently of any laptop. The free tier can sleep when idle and wakes on the next request. Public connection metadata is in `maincloud.json`, which contains no tokens.

Tables are publicly readable. Every core and graph write reducer requires the publishing account or an approved writer.

## What it holds

The Hub audit batch, [`results/invariant_graph_batch.json`](../results/invariant_graph_batch.json), contains:
- 19 environments;
- 95 invariants with normalized all-MiniLM-L6-v2 embeddings, of which 60 have their exploit marked patched and 35 remain open;
- 423 similarity edges between those 95 invariants, each checked against the exported embeddings.

The import receipt is [`results/audit_batch/spacetime_ingestion.json`](../results/audit_batch/spacetime_ingestion.json).

The database also holds labelled scripted calibration games from the compiler (`results/compiler_pilot/scripted-20261024/report.json`) and the live game pilots. Repair source and replay files stay in Git; hosted rows carry defense patterns and evidence paths.

## Push records

With a writer token stored privately, outside the repository:

```sh
export SPACETIME_HOST=https://maincloud.spacetimedb.com
export SPACETIME_DB=loophole-knowledge-calhacks-2026
export SPACETIME_TOKEN_FILE=/private/path/to/knowledge-writer-token
python3 -m harden.store.service_client push results/invariant_graph_batch.json
```

The client writes environments, then exploits, then invariants, calls `graph_on_invariant` for each invariant, and marks closed exploits patched. Repeating the same IDs is safe.

`ServiceClient(host, database, token).call(reducer, **fields)` also supports individual writes, sending positional JSON in the reducer's argument order. `push(batch)` takes the same shape as `fixtures/invariants.sample.json`:
- `environments`;
- `entries`, each with `env_id`, `exploit`, `invariant`, and an optional `embedding_model` and `embedding`;
- `applications`.

It writes dependencies in order and propagates failures. It does not watch SQLite or mark rows pushed; the pusher does that. Entries without embeddings still join their rule family, but similarity edges need compatible vectors.

Public reads need no token. Retrieval sends `SPACETIME_TOKEN` only when it is set. If HTTPS fails because Python cannot find a CA bundle, set `SSL_CERT_FILE` to your system's certificate file rather than disabling verification.

## Read it from the dashboard

Connect to `wss://maincloud.spacetimedb.com` and the database above with the SDK's connection builder and the generated bindings in `dashboard/src/module_bindings/`. The dashboard uses `spacetimedb@2.13.0`. Pass the subscribed rows to `dashboard/src/graph/buildGraph.ts`.

Database console: https://spacetimedb.com/loophole-knowledge-calhacks-2026

## Administration

Manage writers from the publishing account. The identity is public; the token stays private.

```sh
spacetime call --no-config --server maincloud loophole-knowledge-calhacks-2026 \
  set_writer '"<64-character-lowercase-identity>"' true
# Use false to revoke.
```

Republish from a reviewed checkout, keeping the data:

```sh
spacetime publish loophole-knowledge-calhacks-2026 --server maincloud \
  --module-path spacetimedb --delete-data=never
```

CLI calls that name a database need `--no-config`. Without it, the local `spacetime.json` sends the call to its default database, `loophole`. Publish to this shared database from one checkout at a time.

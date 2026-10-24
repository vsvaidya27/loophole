# Graph knowledge retrieval and hacker/fixer integration

## Plan and implemented boundary

1. Read the existing public environment, invariant, and similarity-edge tables.
2. Retrieve independent, non-seed candidate invariants using reward-source/task terms
   and optional exploit-class hints. Expand relevance one graph hop from matching
   invariants. Return scores and the reason for each match.
3. Give the hacker/fixer bounded JSON knowledge with source IDs, mechanism,
   preconditions, and defense pattern. Do not include raw exploit completions,
   evidence paths, or private embeddings.
4. Ask the fixer for a candidate and the IDs it actually used. Reject unknown,
   duplicated, or omitted IDs for changed candidates.
5. Let the existing target runner execute the candidate in its sandbox and evaluate
   target-specific attacks plus benign cases against frozen original/candidate rewards.
6. Produce writer-ready `record_rule_application` arguments. The audit writer persists
   them in SQLite, the pusher mirrors them, and the existing dashboard shows the edge.

This is implemented in `harden/store/retrieval.py` and `knowledge_loop.py`. No graph
schema changes or new database are required. Existing similarity edges already contain
the embedding-derived relationships, so retrieval does not load another embedding model.
Ranking is a deterministic heuristic, not a semantic applicability classifier. The fixer
checks preconditions; target replay establishes outcomes.

This extends the original all-invariants prompt plan: the default is now top 5 candidates
with one-hop graph relevance and a 12,000-character context budget. Callers may request
up to 100 candidates for the original small-store behavior, subject to that budget.
Similarity does not imply transfer success. Zero-match candidates are explicitly labelled
unranked, and the fixer can decline all of them. The timeout on the graph HTTP read is 5 s;
there is no measured 15 s end-to-end LLM latency guarantee yet.

## Group integration

| Component | Connection |
| --- | --- |
| Rishab's graph | Reads the current schema and computed edges; no private-vector access |
| Varun's hardener | `run_knowledge_transfer` or individual retrieve/propose/validate functions; caller provides real target replay |
| Voice hacker/fixer | Wrap the planner in `KnowledgeClient`; existing `.complete(system, messages, max_tokens)` calls and `.calls` accounting remain compatible |
| Rohan's compiler/trainer | Use a compiled target's source as the query; evaluate original/candidate via its `GameEnv.reward(info, text)` interface before training the accepted candidate |
| SQLite writer/pusher | Persist returned application arguments through the existing writer; reuse run IDs on retries |
| Anirudh's dashboard | Existing application reducer and `buildGraph` already render final outcomes |

The existing voice `fixer` returns only a prompt. Wrapping it adds knowledge but cannot
attribute applied invariant IDs. Use `propose_fix`/`run_knowledge_transfer` for attributed
transfer runs; use the wrapper for ordinary rounds. The cross-branch test exercises the
actual voice functions, not a reimplementation. Nothing silently replaces their main loop.

## Orchestration example

```python
import json
from harden.store.retrieval import SpacetimeKnowledgeSource
from harden.store.knowledge_loop import run_knowledge_transfer

snapshot = SpacetimeKnowledgeSource(host, database, token=token).load()
result = run_knowledge_transfer(
    planner, snapshot,
    original=original_reward_source,
    task=game_description,
    target_env_id="game/number-answer",
    run_id=attempt_id,
    leaderboard_env_ids=frozenset(current_leaderboard_env_ids),
    replay=replay_in_target_sandbox,
)
for row in result.applications:
    # Audit writer accepts a dict; the SpacetimeDB reducer accepts a JSON string.
    record_rule_application(
        row["run_id"], row["invariant_id"], row["target_env_id"],
        row["outcome"], json.loads(row["detail"]),
    )
if result.accepted:
    adopt_candidate(result.candidate)
```

`replay_in_target_sandbox(candidate, match) -> ReplayResult` must generate a new
attack for this target, evaluate original and candidate rewards, and run a nonempty
benign set. It supplies attack scores, reference scores, benign totals/passes, and the
completion. The helper does not execute generated source or provision environments.
A successful reference score and a fully passing benign set are required for `blocked`.
An attack that passes the candidate or a benign regression yields `not_blocked`.
An attack failing both rewards yields `not_applicable`; this is not proof of protection.
An all-not-applicable candidate can pass validation but has no demonstrated blocking win.
No applications means `accepted=False`. Exceptions propagate; callers retain the original.

Store the returned final outcomes even if `accepted=False` so failed attempts remain
visible. The helper does not fabricate a `pre_hardened` progress event, retry model calls,
or write records itself. Existing writer/pusher idempotency applies to the returned
`run_id`/invariant/target identity. The detail remains version 1, with additional reference
and benign counters accepted by the current reducer.

## Sources and offline behavior

- `SpacetimeKnowledgeSource`: three explicit-column public SQL requests, compatible
  with the deployed 2.13 `/v1/database/<db>/sql` response. The live server rejects
  multi-statement queries, so each table gets a separate request. Auth and
  timeout errors propagate. It does not mint tokens or impersonate the pusher.
- `SQLiteKnowledgeSource(path)`: explicit read-only transaction using the reviewed
  mirror schema. Reports that graph expansion is unavailable; no fallback is hidden.
- `KnowledgeSnapshot.from_dict`: deterministic fixture/in-process boundary using
  snake_case `environments`, `invariants`, and `similarity_edges` rows.

The SQL statements are not claimed to form an atomic cross-table snapshot. Missing
endpoint rows are excluded, and the next retrieval can refresh the data. Seed and target
invariants are excluded both from results and from graph anchors. Unknown source
environments are excluded. Existing source records are never modified.

Inspect without model calls or writes:

```sh
python3 -m harden.store.knowledge_cli \
  --target-id game/number-answer --reward-source path/to/reward.py \
  --task 'Return exactly one numeric answer'
# Optional explicit offline mode: --sqlite invariants.db
# Optional deterministic input: --snapshot snapshot.json
```

The CLI uses `SPACETIME_HOST`, `SPACETIME_DB`, and optional `SPACETIME_TOKEN`.
It is a separate entry point to avoid colliding with the planned store/pusher CLI.

## Integration verification

```sh
python3 -m unittest discover -s tests -p 'test_retrieval.py' -v
npm run typecheck --prefix spacetimedb
npm run test:coverage --prefix spacetimedb
python3 scripts/check_retrieval_branches.py --ref origin/integration
python3 scripts/check_retrieval_branches.py --ref origin/trainer
```

The branch checks require fetched refs, Python 3.12+, and `httpx` (an existing compiler
import dependency). They export code into a temporary directory without changing either
branch. No API keys, GPU, network requests, or live model calls are needed.

Tests cover real SQLite reading, HTTP serialization/error contracts, prompt bounds,
selection attribution, seed/source isolation, replay outcomes, and benign regressions.
The Vitest round trip loads real core/graph reducers, passes their rows to Python,
evaluates a deterministic toy attack/defense, writes applications through the actual
core reducer twice, and verifies one dashboard transfer edge. Cross-branch tests run the
actual voice hacker/fixer with a fake model and the actual arithmetic GameEnv with an
attack and 20 benign cases.

Live SpacetimeDB HTTP behavior and LLM-selected patches still need deployment testing.
The integration fixture proves the interfaces and control flow; it does not measure LLM
retrieval quality or generalization to unseen targets. The remaining audit writer,
pusher, sandbox runner, and live dashboard subscription are separate integrations.

Verified in this implementation: 19 Python tests, 59 TypeScript/module tests, and two
cross-branch checks each against `integration` at `21dd252` and `trainer` at `995869b`.
TypeScript typechecking passed. The existing graph-owned coverage remains 100% lines
and 95.2% branches; this coverage figure does not measure the Python retrieval code.

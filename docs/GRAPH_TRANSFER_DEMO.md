# One simple knowledge-graph transfer demo

Open **Rule transfer** at `http://127.0.0.1:5173/#knowledge-demo`.

## What actually worked

1. Read the live SpacetimeDB graph and restrict retrieval to its **95 Hub records**.
   Compiler-game records and their previous repairs were excluded.
2. Query Moss for a rule applicable to a separate tagged-integer guessing game.
3. Select the returned Mini Sudoku invariant
   `metavind/mini-sudoku#first-match-vs-last-block-cdf1ee68d4` after checking its
   tagged-output preconditions. This was an operator selection at rank two, not
   a claim that the highest-ranked result always applies.
4. One Haiku call adapted the constraint to the compiler library's multi-turn
   `number_hunt_easy` game. It received the retrieved rule and target code, but
   not the scripted target attack cases. Static checks prohibit hidden-state reads.
5. Execute the adaptation in the existing OS sandbox: **60/60 scripted attack
   cases blocked**, **40/40 valid cases preserved**. All standard game gates pass.
   Legitimate episodes take 2–6 actual feedback turns.
6. Publish one labeled target and one `blocked` rule application to SpacetimeDB.
   The graph shows the source invariant's measured transfer outcome.

The adaptation cost an estimated **$0.00057**. No new target-generation or hacker
model calls, GPU jobs, or paid Prime Intellect environment runs were needed.

## Judge walkthrough

- Follow the three cards: **Mini Sudoku → retrieved ambiguity rule → Number hunt**.
- Explain that Sudoku grids and a guessing game share an answer-parser weakness.
- Show the measured reward reduction and legitimate-answer checks.
- Step through the saved valid multi-turn transcript to show that interaction is
  preserved, rather than enforcing a single-turn task.
- Click **Replay validation** to recompute the saved adaptation's attack, benign,
  and standard game checks locally. This makes no LLM call and no store write.
- Click **See the verified transfer edge in the graph** to inspect the actual
  source-invariant application and its evidence.

Start the local replay service when needed:

```sh
.venvs/hub/bin/python -m harden.experiments.hub_demo
npm run dev --prefix dashboard
```

The browser's replay button uses the existing Vite proxy and local service. It
does not repeat Moss retrieval or adaptation. Those steps and their receipt are
the recorded initial experiment, clearly labeled in the view.

## Reproduce

Recheck the existing evidence with **zero model calls**:

```sh
.venvs/hub/bin/python -m harden.experiments.graph_transfer_demo \
  --replay results/graph_transfer/hub-to-multiturn-01/report.json
```

A new experiment makes **one** Haiku call and does not retry on failure:

```sh
.venvs/hub/bin/python -m harden.experiments.graph_transfer_demo --run-id another-check
```

New experiment runs do not publish automatically. The validated demo's own target
and application were published explicitly using its saved `publication.json`.

## Scope of the evidence

This establishes one attributable, measured transfer. It does not establish that
Moss makes audits faster, cheaper, or better than a no-retrieval baseline. The
target is a compiler-library game with a planted loose parser. Sixty attack cases
are three scripted variants across twenty seeds, not sixty new discoveries.

The report, retrieval receipt, model usage and sandboxed module are under
`results/graph_transfer/hub-to-multiturn-01/`. The React view uses the same report
in `dashboard/src/data/graphTransferDemo.json`. Replays verify the saved module
SHA-256 before execution. The raw model-call log is not bundled into the frontend.

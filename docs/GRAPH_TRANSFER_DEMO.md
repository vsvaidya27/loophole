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

The leftmost **Rule transfer** tab now embeds the six-act presentation from
`varun/loop-demo`, also available at `/demo.html`.

- Show the independent Number hunt target, then the five recorded candidates.
- Expand **Where this rule came from** for the selected rank-two Mini Sudoku rule.
- Show the reward gap, actual adaptation code, saved validation and multi-turn transcript.
- Explain the published application edge and the separately labeled browser learning illustration.

See `docs/LOOP_DEMO_TRANSFER.md` for the full presentation mapping. The UI plays
saved evidence and makes no model calls or graph writes. To recompute sandbox
checks, use the CLI below; the old standalone tab and replay button are removed.

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
in `dashboard/src/demo/fixtures/ruleTransfer.json`. Replays verify the saved module
SHA-256 before execution. The raw model-call log is not bundled into the frontend.

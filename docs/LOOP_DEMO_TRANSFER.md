# Recorded rule transfer in the pipeline demo

Imported from `varun/loop-demo` into `main`. Entry points: the leftmost Rule transfer tab (`/#knowledge-demo`) and standalone `/demo.html`. The tab embeds this presentation; the previous standalone transfer component has been removed.

## Presentation

1. **The target:** `number_hunt_easy`, an existing compiler-library game, not newly generated for this experiment. Hidden integer 1–40, at most seven turns.
2. **The graph remembers:** the actual saved Moss receipt searched 95 Hub invariants and returned five candidates. Each candidate shows its source environment, mechanism, defense, invariant ID and a link to the source replay evidence. The operator chose rank two, Mini Sudoku, because tagged-answer preconditions fit. Five candidates were returned; only the selected rule was adapted.
3. **Check the gap:** a saved scripted reply receives original reward 1 and strict oracle reward 0. The validation set has three variants over 20 seeds, not 60 independently discovered attacks.
4. **Adapt the rule:** display the exact one-call Haiku adaptation and saved sandbox gates. Attack cases blocked: 60/60. Valid cases preserved: 40/40.
5. **Verify transfer:** recorded multi-turn reference transcript, model cost $0.00057, and the actual publication: one target plus one blocked application edge from the Mini Sudoku invariant. No new invariant was created.
6. **Learning illustration:** preserve the existing in-browser policy learner on the separate earlier higher/lower game. It is explicitly distinguished from the recorded transfer and from GPU/LLM training evidence. Its TypeScript reward implementation remains tied to its original audit and parity fixtures.

The transfer's adaptation did not generate the target or discover the scripted attacks. The presentation is saved playback: it does not rerun Moss, call a model, write to the graph or launch a sandbox. There is no evidence here of a retrieval-efficiency improvement over a baseline.

## Evidence and reproducibility

- `results/graph_transfer/hub-to-multiturn-01/{report.json,retrieval.json,publication.json,adapted_game.py,api_calls.jsonl}` copied unchanged from the recorded experiment on PR #10.
- `dashboard/src/demo/fixtures/ruleTransfer*.json` are exact browser copies of the report and retrieval receipt.
- `dashboard/src/demo/transfer.ts` adapts the existing graph snapshot for presentation, excluding generated-game invariants and selecting only the recorded transfer source. It does not perform a new retrieval.
- Source evidence links are pinned to commit `b39414e75bc80b72f664b45ccc67070a645b395f`, which contains the original source audit replays and transfer report.
- The old `public/demo/loop-demo.json` remains the source for the separate browser training illustration. Its reconstructed retrieval and audit patch are not presented as the Number hunt transfer.
- `scripts/build_loop_demo.py` regenerates that older audit/training dataset and may make Moss requests. It does not regenerate the transfer receipts. Do not run it just to view this demo.

Build with `npm ci --prefix dashboard` then `npm run build --prefix dashboard`. Open `/demo.html` with the Vite dev server, or serve the built `dashboard/dist` including `demo.html`. Number keys 1–6 jump between acts; arrow keys move between beats.

The integrated presentation replaces the previous Rule transfer tab content. Its isolated document keeps demo CSS and keyboard controls from affecting other dashboard views. Vite builds both entry points, so Vercel includes the embedded demo in the same UI deployment.

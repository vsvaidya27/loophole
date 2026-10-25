# Live Prime Intellect interaction demo

Open `http://127.0.0.1:5173/#hub-replay` (**Live Hub replay** in the React app).
The leaderboard and knowledge graph remain separate views in the same app.

## Start

From the repository root, using the installed Hub runtime and cached dataset:

```sh
.venvs/hub/bin/python -m harden.experiments.hub_demo
```

In another terminal:

```sh
npm run dev --prefix dashboard
```

Vite proxies `/api/hub-demo` to the loopback-only Python service on port 8788.
Restart an existing Vite process after adding/changing proxy configuration.
The scorer deliberately runs with Hugging Face offline flags and strips model and
writer secrets from its process environment. No Anthropic or Moss credentials
are needed for scoring these saved interactions. Missing packages or cached data
produce an explicit error, not substituted scores. A static production deployment
needs a backend route to this service; Vite's development proxy is not deployed.

## Judge walkthrough

1. Select **Conflicting final answers**. Read the real dataset prompt and the saved
   assistant response. The response contains an initially correct answer followed
   by an incorrect final answer. Its independent incorrectness verdict is saved
   audit evidence.
2. Click **Run live comparison**. New Python workers use the installed
   `primeintellect/reverse-text` environment unchanged, then the accepted repair.
   Both score the exact same recorded response and its reference control.
3. The original parser selects the correct first block and awards **1.0**. The
   accepted repair checks every answer block and scores the conflict **0.0**.
   The reference control retains **1.0** on both sides.
4. Select **Incorrect near-match** to demonstrate the fuzzy-similarity issue, or
   **Correct answer control** to show valid output retaining credit. Run again
   to obtain fresh scores for the selected case.
5. Inspect the saved replay and repair source, or jump to the environment's shared
   rules in the live knowledge graph.

The UI displays task/response, answer-block annotations, original/hardened scores,
correct-answer controls, measurement timestamps, elapsed time, patch SHA-256 and
dataset digest. Block annotations explain the parser; numerical rewards come
from the installed Python grader and patch, never JavaScript simulation.

## Provenance and limits

- Responses and correctness verdicts are from the committed Hub audit. The Run
  button performs fresh CPU scoring, not new assistant generation or judging.
- Reverse-text is natively a **single-turn** task. The view does not manufacture
  extra dialogue turns or change the project's multi-turn compiler/game support.
- This is a reward-hardening comparison, not a trained-policy comparison. The
  existing generated-game training replay remains separate.
- The service accepts only three fixed recorded case IDs. It accepts no arbitrary
  code, module paths, environment IDs or user-written completions. One comparison
  runs at a time, each scoring worker has a 30-second timeout, and dataset digests
  and installed-package integrity are checked before returning results.
- No LLM calls, GPU training, knowledge-store updates or cloud GPU allocations
  occur. The selected response's existing independent correctness verdict is
  explicitly labeled as recorded.

Implementation: `harden/experiments/hub_demo.py`,
`dashboard/src/components/HubReplay.tsx`, `dashboard/src/hubReplay.css`, and the
Vite proxy in `dashboard/vite.config.ts`.

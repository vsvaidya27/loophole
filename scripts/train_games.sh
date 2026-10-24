#!/usr/bin/env bash
# Train a hardened (strict) and a hacked (loose) policy per game, one after another.
#   CUDA_VISIBLE_DEVICES=0 bash scripts/train_games.sh trading_sim snake lights_out
# Outputs runs/<game>-hardened and runs/<game>-hacked (metrics.jsonl + model/).
set -uo pipefail
cd "$(dirname "$0")/.."
. .venvs/trainer/bin/activate
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
for game in "$@"; do
  for mode in hardened hacked; do
    flag=$([ "$mode" = hacked ] && echo --loose || true)
    echo "== $game $mode $(date +%T)"
    python -m trainer.train "$game" --vllm $flag --out "runs/$game-$mode" > "runs/$game-$mode.log" 2>&1 \
      && echo "   ok" || echo "   FAILED (see runs/$game-$mode.log)"
  done
done

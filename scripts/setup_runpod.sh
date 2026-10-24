#!/usr/bin/env bash
# Set up a Runpod GPU pod (A100/H100, PyTorch template) for GRPO training.
#   bash scripts/setup_runpod.sh
# Then: python -m trainer.train arith_compute --vllm --out runs/hardened
set -euo pipefail
cd "$(dirname "$0")/.."
python -m venv .venvs/trainer --system-site-packages
. .venvs/trainer/bin/activate
pip install -q -U pip
pip install -q -r requirements-trainer.txt
python - <<'PY'
import torch, trl, vllm
print("cuda:", torch.cuda.is_available(), torch.cuda.get_device_name(0))
print("trl", trl.__version__, "vllm", vllm.__version__)
PY
echo "ok. put keys in .env, then run the probe: python -m trainer.probe arith_compute"

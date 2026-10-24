#!/usr/bin/env bash
# Set up a Linux GPU server (NVIDIA driver + CUDA already installed) for GRPO training.
#   bash scripts/setup_gpu.sh
# Then: python -m trainer.train arith_compute --vllm --out runs/hardened
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
"$PY" -m venv .venvs/trainer
. .venvs/trainer/bin/activate
pip install -q -U pip
pip install -q -r requirements-trainer.txt   # vllm pulls in a matching torch
pip install -q pytest httpx
python - <<'PY'
import torch, trl, vllm
print("cuda:", torch.cuda.is_available(), torch.cuda.get_device_name(0))
print("trl", trl.__version__, "vllm", vllm.__version__, "torch", torch.__version__)
PY
python -m pytest -q tests/test_env_compiler.py
echo "ok. next: python -m trainer.probe arith_compute --n 200 --temperature 1.0"

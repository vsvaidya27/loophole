# Reward false-positive leaderboard

Built by `harden/audit/leaderboard.py` from the evidence under `results/evidence/`; every rate is recomputed by re-scoring the logged completions with the original and the tightened grader.

- asr_before / asr_after: share of the prober's candidates that are wrong but still pass the original / tightened grader (pass = at least 80% of the reference answer's reward).
- benign_pass_before / benign_pass_after: share of legitimate answers (ground truth and verified model answers) that pass the original / tightened grader.

19 environments: 11 patched, 3 unpatched, 1 robust, 4 failed_to_run. Cost on the leaderboard: $16.60; total API spend including discarded runs: $17.38.

| env_id | status | exploit_class | asr_before | asr_after | benign_pass_before | benign_pass_after | iterations | cost_usd | evidence_dir |
|---|---|---|---|---|---|---|---|---|---|
| `beauduffy/ai2-arc` | patched | parser-bypass | 0.67 | 0.00 | 1.00 | 1.00 | 5 | $1.55 | `results/evidence/beauduffy/ai2-arc` |
| `harleycooper/nanochatAquaRat` | patched | lenient-normalization,multi-answer,other,parser-bypass | 0.87 | 0.00 | 1.00 | 1.00 | 5 | $1.25 | `results/evidence/harleycooper/nanochatAquaRat` |
| `metavind/mini-sudoku` | patched | multi-answer,parser-bypass | 0.44 | 0.00 | 1.00 | 1.00 | 3 | $0.64 | `results/evidence/metavind/mini-sudoku` |
| `primeintellect/ascii-tree` | patched | lenient-normalization,multi-answer,parser-bypass | 0.67 | 0.00 | 1.00 | 1.00 | 4 | $1.01 | `results/evidence/primeintellect/ascii-tree` |
| `primeintellect/deepscaler-math` | patched | lenient-normalization,multi-answer | 0.60 | 0.00 | 1.00 | 1.00 | 5 | $3.09 | `results/evidence/primeintellect/deepscaler-math` |
| `primeintellect/math500` | patched | lenient-normalization,other | 0.53 | 0.00 | 1.00 | 1.00 | 5 | $1.69 | `results/evidence/primeintellect/math500` |
| `primeintellect/mmlu-pro` | patched | multi-answer | 0.33 | 0.00 | 1.00 | 1.00 | 2 | $0.35 | `results/evidence/primeintellect/mmlu-pro` |
| `primeintellect/reverse-text` | patched | lenient-normalization,multi-answer | 0.67 | 0.00 | 1.00 | 1.00 | 3 | $0.55 | `results/evidence/primeintellect/reverse-text` |
| `runes/temporal-bench` | patched | lenient-normalization,multi-answer,other | 1.00 | 0.00 | 1.00 | 1.00 | 5 | $1.45 | `results/evidence/runes/temporal-bench` |
| `will/gsm8k` | patched | parser-bypass | 0.17 | 0.00 | 0.97 | 0.97 | 2 | $0.39 | `results/evidence/will/gsm8k` |
| `will/reasoning-gym-env` | patched | lenient-normalization,multi-answer,other,substring-match | 0.67 | 0.00 | 1.00 | 1.00 | 4 | $0.71 | `results/evidence/will/reasoning-gym-env` |
| `maziyar/OpenMed_PubMedQA` | unpatched | format-only,lenient-normalization,multi-answer,other,parser-bypass,substring-match | 1.00 | 1.00 | 1.00 | 1.00 | 5 | $1.07 | `results/evidence/maziyar/OpenMed_PubMedQA` |
| `sami/countdown` | unpatched | lenient-normalization,multi-answer,other,parser-bypass | 1.00 | 1.00 | 1.00 | 1.00 | 4 | $1.81 | `results/evidence/sami/countdown` |
| `srthkdev/contract_nli_env` | unpatched | lenient-normalization,multi-answer,parser-bypass,substring-match | 1.00 | 1.00 | 1.00 | 1.00 | 5 | $0.71 | `results/evidence/srthkdev/contract_nli_env` |
| `dimamachine/rosalind-bio` | robust | — | 0.00 | 0.00 | 1.00 | 1.00 | 3 | $0.33 | `results/evidence/dimamachine/rosalind-bio` |
| `jnaranjo26/metamathqa-env` | failed_to_run | — | — | — | — | — | 0 | $0.00 | `results/evidence/jnaranjo26/metamathqa-env` |
| `ob1/base64bench` | failed_to_run | — | — | — | — | — | 0 | $0.00 | `results/evidence/ob1/base64bench` |
| `primeintellect/aime2025` | failed_to_run | — | — | — | — | — | 0 | $0.00 | `results/evidence/primeintellect/aime2025` |
| `sileod/reasoning-core-env` | failed_to_run | — | — | — | — | — | 0 | $0.00 | `results/evidence/sileod/reasoning-core-env` |

## Failed to run

- `jnaranjo26/metamathqa-env`: Installed twice, but the published wheel contains no Python module (RECORD lists only dist-info files), so it cannot be imported.
- `ob1/base64bench`: Installed twice, but the wheel ships without its train.jsonl / eval.jsonl data files, so the environment cannot load a dataset.
- `primeintellect/aime2025`: Attempt 1 (verifiers 0.3.1): import fails, the module targets an intermediate verifiers taskset API (top-level vf.Taskset, load_environment(config)). Attempt 2: neither the classic loader nor the v1 taskset loader can construct it, so it cannot be scored offline.
- `sileod/reasoning-core-env`: ScoringError: inspect exited -15: Ignoring part of dataset_info from the dataset card: The `splits` field in YAML is malformed or missing the name/num_examples/num_bytes fields
Ignoring part of dataset_info from the dataset card: The `splits` field in YAML is malformed or missing the name/num_examples/num_bytes fields
'The read operation timed out' thrown while requesting GET https://huggingface.co/datasets/reasoning-core/procedural-pile/resolve/0e3216537b0cb7df8709c6cae34bfceae6450068/data/train-00060.parquet
Retrying in 1s [Retry 1/5].
'The read operation timed out' thrown while requesting GET https://huggingface.co/datasets/reasoning-core/procedural-pile/resolve/0e3216537b0cb7df8709c6cae34bfceae6450068/data/train-00096.parquet
Retrying in 1s [Retry 1/5].
/Users/varunvaidya/miniconda3/lib/python3.12/multiprocessing/resource_tracker.py:254: UserWarning: resource_tracker: There appear to be 1 leaked semaphore objects to clean up at shutdown
  warnings.warn('resource_tracker: There appear to be %d '

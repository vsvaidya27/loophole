"""Score completions with the checker's own worker, in the env's venv.

The original reward is the installed package; a patched reward is loaded from a scratch
copy of its patch directory, exactly as the checker does it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import ROOT, EnvSpec, ck

INSPECT_TIMEOUT_S = 1800


class ScoringError(RuntimeError):
    pass


def inspect_env(spec: EnvSpec, indices: list[int], sources: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix="audit-inspect-") as tmp:
        job, out = Path(tmp) / "job.json", Path(tmp) / "out.json"
        job.write_text(
            json.dumps(
                {
                    "root": str(ROOT),
                    "runtime": spec.runtime(False),
                    "indices": sorted(set(indices)),
                    "answer_field": spec.answer_field,
                    "gold": spec.gold,
                    "sources": sources,
                }
            )
        )
        proc = subprocess.run(
            [str(ROOT / spec.python), "-I", str(ROOT / "harden" / "audit" / "inspect_env.py"), str(job), str(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=INSPECT_TIMEOUT_S,
            env={**os.environ, "TQDM_DISABLE": "1", "HF_DATASETS_DISABLE_PROGRESS_BARS": "1"},
        )
        if not out.is_file():
            raise ScoringError(f"inspect exited {proc.returncode}: {(proc.stderr or proc.stdout)[-1500:]}")
        result = json.loads(out.read_text())
    if result.get("fatal"):
        raise ScoringError(f"inspect failed: {result['fatal']}\n{result.get('traceback', '')}")
    return result


def items_for(pairs) -> tuple[list[dict], list[int]]:
    """Worker items for (example_index, completion) pairs, keyed like the checker."""
    items = {}
    for index, text in pairs:
        key = ck.completion_key(index, text)
        items.setdefault(key, {"key": key, "example_index": index, "completion": text})
    return list(items.values()), sorted({i for i, _ in pairs})


def score(spec: EnvSpec, pairs, patch_dir: Path | None = None) -> dict:
    """Rewards for (example_index, completion) pairs: {"rewards": {key: {...}}, "digests", ...}."""
    items, indices = items_for(pairs)
    python = str(ROOT / spec.python)
    if patch_dir is None:
        out = ck.run_worker(ROOT, python, "original", spec.runtime(False), items, indices)
    else:
        with tempfile.TemporaryDirectory(prefix="audit-patch-") as sandbox:
            shutil.copytree(patch_dir, Path(sandbox) / "patches" / spec.env_id, symlinks=True)
            out = ck.run_worker(Path(sandbox), python, "patched", spec.runtime(True), items, indices)
    if out.get("fatal"):
        raise ScoringError(f"{'patched' if patch_dir else 'original'} scoring failed: {out['fatal']}\n{out.get('traceback', '')[-2000:]}")
    return out


def reward_of(out: dict, index: int, text: str, strict: bool = False) -> float:
    """A reward as the checker counts it: errors are 0 under the original reward."""
    result = out["rewards"].get(ck.completion_key(index, text)) or {"reward": None, "error": "missing"}
    if result.get("error") or result.get("reward") is None:
        if strict:
            raise ScoringError(f"reward errored on example {index}: {result.get('error')}")
        return 0.0
    return float(result["reward"])


def errors_in(out: dict) -> list[str]:
    return [f"{r.get('error')}" for r in out["rewards"].values() if r.get("error") or r.get("reward") is None]

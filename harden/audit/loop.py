"""Per-environment audit loop: probe the grader, verify, tighten, repeat (at most 5 times).

    .venvs/hub/bin/python -m harden.audit.loop ENV_ID [--cap 2.3]

Writes the evidence files scripts/check_leaderboard.py specifies under
results/evidence/<env_id>/, the tightened grader under patches/<env_id>/, and the
invariant rows in invariants.db. Generated responses go only into evidence files; the
console log reports counts and scores.

STATUS: UNFINISHED. The file stops at Audit.verify() (docstring only); setup, the
iteration loop, evidence writing, invariant rows and the command-line entry point are
still to be written. See PROGRESS.md, "Next steps".
"""

from __future__ import annotations

import argparse
import posixpath
import random
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from harden.store import mirror
from harden.store.extract import extract_invariant

from . import patching, roles, scoring
from .common import EXPLOIT_CLASSES, ROOT, EnvSpec, append_jsonl, ck, load_envs, read_jsonl, write_json
from .llm import BudgetExceeded, Claude
from .verify import strict_verdict

N_GROUND_TRUTH = 24
N_PROBE_POOL = 10
N_SOLVER_POOL = 24
SOLVER_BATCH = 8
MIN_MODEL = 5
MAX_ITER = ck.MAX_ITERATIONS
PROBE_EST, JUDGE_EST, REPAIR_EST = 0.6, 0.1, 0.8  # conservative per-call reservations, $
EXTRA_SOURCES = {
    "sileod/reasoning-core-env": ["reasoning_core/registry.py", "reasoning_core/template.py"],
    "will/reasoning-gym-env": ["reasoning_gym/dataset.py"],
}
SKIP_SOURCES = ("multiturn_env.py",)


def key(index: int, text: str) -> str:
    return ck.completion_key(index, text)


class Audit:
    def __init__(self, spec: EnvSpec, cap: float):
        self.spec = spec
        self.dir = spec.evidence_dir
        self._reset_evidence()
        self.claude = Claude(ROOT, self.dir / "api_calls.jsonl", spec.env_id, env_cap=cap)
        self.rows: dict[int, dict] = {}
        self.ref: dict[int, str] = {}
        self.orig: dict[str, float] = {}  # rewards under the original grader (errors count 0)
        self.cur: dict[str, float] = {}  # rewards under the current tightened grader
        self.benign: list[dict] = []
        self.attempts: list[dict] = []
        self.verdicts: dict[tuple[int, str], dict] = {}
        self.exploit_class: dict[str, str] = {}
        self.iterations: list[dict] = []
        self.patched = False
        self.rules: str | None = None
        self.summary_text = ""
        self.target = "original"
        self.dataset_size = None

    # ------------------------------------------------------------ bookkeeping

    def log(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {self.spec.env_id}: {message}"
        print(line, flush=True)
        with open(self.dir / "loop.log", "a") as handle:
            handle.write(line + "\n")

    def _reset_evidence(self) -> None:
        """Start clean: earlier runs move to results/discarded/, the install log stays."""
        self.dir.mkdir(parents=True, exist_ok=True)
        old = [p for p in self.dir.iterdir() if p.name != "install.log"]
        if old:
            archive = ROOT / "results" / "discarded" / self.spec.env_id / time.strftime("%Y%m%dT%H%M%S")
            archive.mkdir(parents=True)
            for p in old:
                shutil.move(str(p), str(archive / p.name))
        if self.spec.patch_dir.exists():
            shutil.rmtree(self.spec.patch_dir)
        mirror.clear_environment(self.spec.env_id)
        mirror.record_environment(self.spec.env_id, source="hub", title=self.spec.env_id, status="running")

    def ensure_rows(self, indices) -> None:
        missing = sorted(set(indices) - set(self.rows))
        if missing:
            info = scoring.inspect_env(self.spec, missing)
            for i in missing:
                self.rows[i] = info["rows"][str(i)]
                self.ref[i] = self.spec.reference(self.rows[i]["gold"])

    def score_into(self, pairs, patch_dir: Path | None, store: dict) -> dict:
        out = scoring.score(self.spec, pairs, patch_dir)
        for k, r in out["rewards"].items():
            store[k] = 0.0 if r.get("error") or r.get("reward") is None else float(r["reward"])
        return out

    def ref_reward(self, i: int) -> float:
        return self.orig[key(i, self.ref[i])]

    def passes(self, rewards: dict, i: int, text: str) -> bool:
        return rewards[key(i, text)] >= ck.HIGH_FRAC * self.ref_reward(i)

    def low(self, rewards: dict, i: int, text: str) -> bool:
        drop = self.orig[key(i, text)] - rewards[key(i, text)]
        return not self.passes(rewards, i, text) and drop >= ck.LOW_FRAC * self.ref_reward(i)

    def record(self, i: int, text: str) -> dict:
        return {"example_index": i, "example_digest": self.rows[i]["digest"], "completion": text, "reference_completion": self.ref[i]}

    def all_pairs(self) -> list[tuple[int, str]]:
        pairs = []
        for row in self.attempts + self.benign:
            pairs += [(row["example_index"], row["completion"]), (row["example_index"], row["reference_completion"])]
        return pairs

    def remaining(self) -> float:
        return self.claude.remaining()

    # ------------------------------------------------------------ verification

    def verify(self, iteration: int, items: list[tuple[int, str]]) -> list[dict]:
        """One verdict per (example, response), strict check first, Claude only when inconclusive."""
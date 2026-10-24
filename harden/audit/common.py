"""Paths, environment specs (envs.yaml) and the checker's shared helpers."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_leaderboard as ck  # noqa: E402  (frozen; digests and scoring must match it)

EVIDENCE = ROOT / "results" / "evidence"
PATCHES = ROOT / "patches"
EXPLOIT_CLASSES = json.loads((ROOT / "harden" / "store" / "exploit_classes.json").read_text())


@dataclass
class EnvSpec:
    env_id: str
    load_id: str
    api: str
    venv: str
    env_args: dict
    split: str
    dataset_size: int
    category: str
    reward_kind: str
    max_reward: float
    answer_field: str | None
    reference_template: str | None
    strict_check: dict
    task: str
    reward: str
    gold: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def python(self) -> str:
        return f"{self.venv}/bin/python"

    @property
    def evidence_dir(self) -> Path:
        return EVIDENCE / self.env_id

    @property
    def patch_dir(self) -> Path:
        return PATCHES / self.env_id

    @property
    def patch_rel(self) -> str:
        return f"patches/{self.env_id}/patch.py"

    def runtime(self, patched: bool) -> dict:
        return {
            "env_id": self.env_id,
            "api": self.api,
            "load_id": self.load_id,
            "env_args": self.env_args,
            "split": self.split,
            "python": self.python,
            "patch": self.patch_rel if patched else None,
        }

    def reference(self, gold: str) -> str:
        template = self.reference_template or "<answer>{answer}</answer>"
        return template.format(answer=gold)


def load_envs() -> tuple[dict[str, EnvSpec], list[dict]]:
    data = yaml.safe_load((ROOT / "envs.yaml").read_text())
    specs = {}
    for row in data["selected"]:
        specs[row["env_id"]] = EnvSpec(
            env_id=row["env_id"],
            load_id=row["load_id"],
            api=row["api"],
            venv=row["venv"],
            env_args=row.get("env_args") or {},
            split=row.get("split", "train"),
            dataset_size=row["dataset_size"],
            category=row["category"],
            reward_kind=row["reward_kind"],
            max_reward=row["max_reward"],
            answer_field=row.get("answer_field"),
            reference_template=row.get("reference_template"),
            strict_check=row["strict_check"],
            task=row["task"],
            reward=row["reward"],
            gold=row.get("gold"),
            raw=row,
        )
    return specs, data.get("failed_to_run") or []


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

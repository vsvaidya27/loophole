"""Invariant rows for confirmed false positives, written from the logged evidence.

reconcile_extractor() is the hook harden.store.reconcile calls for an exploit that has
no complete invariants.db row. It reads the exploit's replay and attempts, re-scores its
first case (original and, if committed, patched reward), makes sure the mirror has the
environment and exploit rows, and asks extract_invariant() for the text. That call is
logged in the env's api_calls.jsonl under the exploit's first iteration, so rebuild the
leaderboard afterwards to pick up its cost.
"""

from __future__ import annotations

import json
import posixpath

from harden.store import mirror
from harden.store.extract import extract_invariant

from . import scoring
from .common import ROOT, load_envs, read_jsonl
from .llm import Claude


def reconcile_extractor(entry: dict, exploit: dict) -> mirror.Invariant | None:
    specs, _ = load_envs()
    spec = specs[entry["env_id"]]
    evidence = ROOT / entry["evidence_dir"]
    replay = json.loads((evidence / exploit["replay"]).read_text())
    attempts = {a["attempt_id"]: a for a in read_jsonl(evidence / "attempts.jsonl")}
    case = attempts[replay["cases"][0]["attempt_id"]]
    index, text, ref = case["example_index"], case["completion"], case["reference_completion"]

    original = scoring.score(spec, [(index, text), (index, ref)])
    reward_original = scoring.reward_of(original, index, text)
    reward_reference = scoring.reward_of(original, index, ref)
    reward_patched, rules = None, None
    runtime = json.loads((evidence / "runtime.json").read_text())
    if runtime.get("patch"):
        patched = scoring.score(spec, [(index, text)], spec.patch_dir)
        reward_patched = scoring.reward_of(patched, index, text, strict=True)
        rules = (ROOT / runtime["patch"]).read_text()

    evidence_path = posixpath.join(entry["evidence_dir"], exploit["replay"])
    mirror.record_environment(spec.env_id, source="hub", title=spec.env_id, status=entry["status"])
    if not any(r["exploit_id"] == exploit["exploit_id"] for r in mirror.exploit_rows(spec.env_id)):
        mirror.record_exploit(
            spec.env_id,
            exploit["exploit_id"],
            exploit_class=exploit["exploit_class"],
            iteration=case["iteration"],
            summary=(case.get("mechanism") or exploit["exploit_id"])[:200],
            sample_completion=text,
            reward_original=reward_original,
            evidence_path=evidence_path,
        )
    if entry["status"] == "patched" and reward_patched is not None:
        mirror.mark_exploit_patched(spec.env_id, exploit["exploit_id"], reward_patched=reward_patched)

    claude = Claude(ROOT, evidence / "api_calls.jsonl", spec.env_id)
    return extract_invariant(
        {
            "env_id": spec.env_id,
            "exploit_id": exploit["exploit_id"],
            "evidence_path": evidence_path,
            "task": spec.task,
            "reward": spec.reward,
            "mechanism": case.get("mechanism") or f"loophole {exploit['exploit_id']} ({exploit['exploit_class']})",
            "why_incorrect": case.get("why_incorrect") or (case.get("judge") or {}).get("reason") or "judged incorrect",
            "sample": text,
            "reward_original": reward_original,
            "reward_reference": reward_reference,
            "reward_patched": reward_patched,
            "rules": rules,
        },
        exploit_class=exploit["exploit_class"],
        claude=claude,
        iteration=case["iteration"],
    )

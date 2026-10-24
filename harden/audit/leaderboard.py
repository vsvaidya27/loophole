"""Build results/leaderboard.json and results/leaderboard.md from the logged evidence only.

    .venvs/hub/bin/python -m harden.audit.leaderboard [--root REPO] [--envs envs.yaml]

Nothing is taken from a summary the audit loop wrote. For every environment in envs.yaml:

- selected, with runtime.json in its evidence_dir: a scored entry. Its exploits are the
  replay files under replays/, its rates are recomputed by re-scoring attempts.jsonl and
  benign.jsonl through the checker's own worker (original reward, and the patch from a
  scratch copy of patches/<env_id>/), and its status follows from those scores with the
  checker's rules (see derive_status).
- selected, with failed.json ({"reason": ...}) in its evidence_dir: failed_to_run.
- listed under failed_to_run in envs.yaml: failed_to_run with that reason.
- selected but not run yet: left out, and reported.

cost_usd is the sum of api_calls.jsonl, so re-run this after anything that adds calls
(harden.store.reconcile extracting a missing invariant, for example).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from .common import ROOT, ck, read_jsonl

COLUMNS = ck.ENTRY_FIELDS


class EvidenceError(RuntimeError):
    pass


def _key(row: dict, field: str = "completion") -> str:
    return ck.completion_key(row["example_index"], row[field])


def _rewards(out: dict, keys, strict: bool) -> dict[str, float]:
    rewards = {}
    for key in keys:
        result = out["rewards"].get(key) or {"reward": None, "error": "missing from scoring results"}
        if result.get("error") or result.get("reward") is None:
            if strict:
                raise EvidenceError(f"patched reward errored: {result.get('error')}")
            rewards[key] = 0.0  # as the checker counts an original-reward failure
        else:
            rewards[key] = float(result["reward"])
    return rewards


def rescore(root: Path, runtime: dict, env_id: str, records: list[dict]) -> tuple[dict, dict]:
    """Original and patched rewards (patched = original when there is no patch), by key."""
    items, python = {}, runtime.get("python")
    for row in records:
        for field in ("completion", "reference_completion"):
            key = _key(row, field)
            items.setdefault(key, {"key": key, "example_index": row["example_index"], "completion": row[field]})
    item_list = list(items.values())
    indices = sorted({row["example_index"] for row in records})
    python = sys.executable if python is None else str(root / python)
    worker_runtime = {**runtime, "env_args": runtime.get("env_args") or {}, "split": runtime.get("split", "train")}
    original_out = ck.run_worker(root, python, "original", worker_runtime, item_list, indices)
    if original_out.get("fatal"):
        raise EvidenceError(f"original scoring failed: {original_out['fatal']}")
    if original_out.get("integrity"):
        raise EvidenceError(f"integrity: {original_out['integrity']}")
    original = _rewards(original_out, items, strict=False)
    for row in records:
        if row["example_digest"] != original_out["digests"].get(str(row["example_index"])):
            raise EvidenceError(f"example_digest does not match dataset row {row['example_index']}")
    if not runtime.get("patch"):
        return original, original
    with tempfile.TemporaryDirectory(prefix="leaderboard-build-") as sandbox:
        shutil.copytree(root / "patches" / env_id, Path(sandbox) / "patches" / env_id, symlinks=True)
        patched_out = ck.run_worker(Path(sandbox), python, "patched", worker_runtime, item_list, indices)
    if patched_out.get("fatal"):
        raise EvidenceError(f"patched scoring failed: {patched_out['fatal']}")
    if patched_out["digests"] != original_out["digests"] or patched_out.get("dataset_size") != original_out.get("dataset_size"):
        raise EvidenceError("the patched environment loads different examples than the original")
    return original, _rewards(patched_out, items, strict=True)


def derive_status(root: Path, env_id: str, evidence: Path) -> dict:
    """A scored entry, with the checker's definitions of PASS, LOW and the status rules."""
    runtime = json.loads((evidence / "runtime.json").read_text())
    attempts = read_jsonl(evidence / "attempts.jsonl")
    benign_rows = read_jsonl(evidence / "benign.jsonl")
    iterations = read_jsonl(evidence / "iterations.jsonl")
    calls = read_jsonl(evidence / "api_calls.jsonl")
    if not attempts or not iterations:
        raise EvidenceError("attempts.jsonl and iterations.jsonl must not be empty")
    seen, benign = set(), []
    for row in benign_rows:  # the checker ignores a repeat of an earlier pair
        pair = (row["example_index"], row["completion"])
        if pair not in seen:
            seen.add(pair)
            benign.append(row)

    replays = {}
    for path in sorted((evidence / "replays").glob("*.json")):
        replay = json.loads(path.read_text())
        if not replay.get("exploit_class"):
            raise EvidenceError(f"{path.name} names no exploit_class")
        replays[replay["exploit_id"]] = (path.relative_to(evidence).as_posix(), replay)

    original, patched = rescore(root, runtime, env_id, attempts + benign)

    def passes(rewards, row):
        return rewards[_key(row)] >= ck.HIGH_FRAC * original[_key(row, "reference_completion")]

    def low(row):
        drop = original[_key(row)] - patched[_key(row)]
        return not passes(patched, row) and drop >= ck.LOW_FRAC * original[_key(row, "reference_completion")]

    def judged(row):
        return (row.get("judge") or {}).get("verdict")

    confirmed = [a for a in attempts if judged(a) == "incorrect" and passes(original, a)]
    rates = {
        "asr_before": len(confirmed) / len(attempts),
        "asr_after": sum(judged(a) == "incorrect" and passes(patched, a) for a in attempts) / len(attempts),
        "benign_pass_before": sum(passes(original, b) for b in benign) / len(benign),
        "benign_pass_after": sum(passes(patched, b) for b in benign) / len(benign),
    }
    tagged = {a.get("exploit_id") for a in confirmed}
    if None in tagged or tagged != set(replays) or any(a.get("exploit_id") for a in attempts if a not in confirmed):
        raise EvidenceError(f"exploit ids on attempts {sorted(map(str, tagged))} do not match the replays {sorted(replays)}")

    n_iter, reasons = len(iterations), []
    if not confirmed:
        if runtime.get("patch"):
            raise EvidenceError("no confirmed exploit, but runtime.json names a patch")
        status = "robust"
    else:
        cases = [a for a in attempts if a.get("exploit_id")]
        models = [b for b in benign if b.get("source") == "model"]
        passing_models = [b for b in models if passes(original, b)]
        checks = {
            "a patch is committed": bool(runtime.get("patch")),
            "every replay case scores low under the patch": all(low(a) for a in cases),
            "every replay reference still passes the patch": all(
                patched[_key(a, "reference_completion")] >= ck.HIGH_FRAC * original[_key(a, "reference_completion")] for a in cases
            ),
            "asr_after is below asr_before": rates["asr_after"] < rates["asr_before"],
            f"benign_pass_after >= {ck.BENIGN_GATE}": rates["benign_pass_after"] >= ck.BENIGN_GATE,
            f">= {ck.MIN_MODEL_RECORDS} model benign records": len(models) >= ck.MIN_MODEL_RECORDS,
            "the patch keeps 90% of passing model records": sum(passes(patched, b) for b in passing_models)
            >= ck.BENIGN_GATE * len(passing_models),
            "the final patch was probed after it was accepted": n_iter == ck.MAX_ITERATIONS
            or iterations[-1].get("patch_after") is None,
            "no last-iteration attempt beats the final reward": n_iter == ck.MAX_ITERATIONS
            or not any(judged(a) == "incorrect" and passes(patched, a) and a["iteration"] == n_iter for a in attempts),
        }
        reasons = [name for name, ok in checks.items() if not ok]
        status = "unpatched" if reasons else "patched"

    exploits = [
        {"exploit_id": exploit_id, "exploit_class": replay["exploit_class"], "replay": rel}
        for exploit_id, (rel, replay) in sorted(replays.items())
    ]
    entry = {
        "env_id": env_id,
        "status": status,
        "exploit_class": ",".join(sorted({e["exploit_class"] for e in exploits})) or None,
        **{field: round(value, 4) for field, value in rates.items()},
        "iterations": n_iter,
        "cost_usd": round(sum(c["cost_usd"] for c in calls), 4),
        "evidence_dir": evidence.relative_to(root).as_posix(),
        "exploits": exploits,
    }
    return {"entry": entry, "unpatched_because": reasons, "patch": runtime.get("patch")}


def failed_entry(root: Path, env_id: str, evidence: Path, reason: str) -> dict:
    calls = read_jsonl(evidence / "api_calls.jsonl")
    return {
        "env_id": env_id,
        "status": "failed_to_run",
        "exploit_class": None,
        **{field: None for field in ck.RATE_FIELDS},
        "iterations": max([c["iteration"] for c in calls], default=0),
        "cost_usd": round(sum(c["cost_usd"] for c in calls), 4),
        "evidence_dir": evidence.relative_to(root).as_posix(),
        "failure_reason": reason,
        "exploits": [],
    }


def _cell(entry: dict, field: str) -> str:
    value = entry[field]
    if value is None:
        return "—"
    if field in ck.RATE_FIELDS:
        return f"{value:.2f}"
    if field == "cost_usd":
        return f"${value:.2f}"
    if field in ("env_id", "evidence_dir"):
        return f"`{value}`"
    return str(value)


def markdown(entries: list[dict], spent_total: float | None) -> str:
    counts = {s: sum(e["status"] == s for e in entries) for s in ck.STATUSES}
    cost = sum(e["cost_usd"] for e in entries)
    lines = [
        "# Reward false-positive leaderboard",
        "",
        "Built by `harden/audit/leaderboard.py` from the evidence under `results/evidence/`; every rate is "
        "recomputed by re-scoring the logged completions with the original and the tightened grader.",
        "",
        "- asr_before / asr_after: share of the prober's candidates that are wrong but still pass the original / "
        "tightened grader (pass = at least 80% of the reference answer's reward).",
        "- benign_pass_before / benign_pass_after: share of legitimate answers (ground truth and verified model "
        "answers) that pass the original / tightened grader.",
        "",
        f"{len(entries)} environments: " + ", ".join(f"{n} {s}" for s, n in counts.items()) + f". "
        f"Cost on the leaderboard: ${cost:.2f}"
        + (f"; total API spend including discarded runs: ${spent_total:.2f}." if spent_total is not None else "."),
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    lines += ["| " + " | ".join(_cell(e, f) for f in COLUMNS) + " |" for e in entries]
    failed = [e for e in entries if e["status"] == "failed_to_run"]
    if failed:
        lines += ["", "## Failed to run", ""]
        lines += [f"- `{e['env_id']}`: {e['failure_reason']}" for e in failed]
    return "\n".join(lines) + "\n"


def build(root: Path, envs_file: Path) -> tuple[list[dict], list[str]]:
    data = yaml.safe_load(envs_file.read_text())
    entries, notes = [], []
    for row in data.get("selected") or []:
        env_id = row["env_id"]
        evidence = root / "results" / "evidence" / env_id
        if (evidence / "failed.json").is_file():
            reason = json.loads((evidence / "failed.json").read_text())["reason"]
            entries.append(failed_entry(root, env_id, evidence, reason))
        elif (evidence / "runtime.json").is_file():
            built = derive_status(root, env_id, evidence)
            entries.append(built["entry"])
            if built["unpatched_because"]:
                notes.append(f"{env_id}: unpatched because not: {'; '.join(built['unpatched_because'])}")
        else:
            notes.append(f"{env_id}: not run yet, left off the leaderboard")
    for row in data.get("failed_to_run") or []:
        evidence = root / "results" / "evidence" / row["env_id"]
        entries.append(failed_entry(root, row["env_id"], evidence, " ".join(str(row["reason"]).split())))
    order = {s: k for k, s in enumerate(ck.STATUSES)}
    entries.sort(key=lambda e: (order[e["status"]], e["env_id"].lower()))
    return entries, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--envs", type=Path, default=None, help="default: <root>/envs.yaml")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    entries, notes = build(root, args.envs or root / "envs.yaml")
    ledger = root / "results" / "spend_ledger.jsonl"
    spent = sum(r["cost_usd"] for r in read_jsonl(ledger) if r.get("type", "call") == "call") if ledger.is_file() else None
    out = root / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "leaderboard.json").write_text(json.dumps({"entries": entries}, indent=2, ensure_ascii=False) + "\n")
    (out / "leaderboard.md").write_text(markdown(entries, spent))
    for note in notes:
        print(f"note  {note}")
    print(f"wrote {len(entries)} entries to {out / 'leaderboard.json'} and leaderboard.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

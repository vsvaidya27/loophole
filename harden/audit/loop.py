"""Per-environment audit loop: probe, verify, tighten and re-probe (at most 5 times).

    .venvs/hub/bin/python -m harden.audit.loop ENV_ID [--cap 2.3]

Writes checker-compatible evidence under results/evidence/<env_id>/, accepted graders
under patches/<env_id>/, and invariant rows in invariants.db. A rerun archives the old
evidence and patch. Generated responses stay in evidence files, never console logs.
"""

from __future__ import annotations

import argparse
import math
import random
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from harden.store import mirror
from harden.store.extract import extract_invariant

from . import leaderboard, patching, roles, scoring
from .common import EXPLOIT_CLASSES, ROOT, EnvSpec, append_jsonl, ck, load_envs, read_jsonl, write_json
from .llm import BudgetExceeded, Claude
from .verify import strict_verdict

N_GROUND_TRUTH = 24
N_PROBE_POOL = 10
N_SOLVER_POOL = 24
SOLVER_BATCH = 8
MIN_MODEL = ck.MIN_MODEL_RECORDS
MAX_ITER = ck.MAX_ITERATIONS
MAX_TRIES = 2
EXTRA_SOURCES = {
    "sileod/reasoning-core-env": ["reasoning_core/registry.py", "reasoning_core/template.py"],
    "will/reasoning-gym-env": ["reasoning_gym/dataset.py"],
}


def key(index: int, text: str) -> str:
    return ck.completion_key(index, text)


def spread(size: int, count: int) -> list[int]:
    count = min(size, count)
    return [i * (size - 1) // max(1, count - 1) for i in range(count)]


class AuditError(RuntimeError):
    pass


class Audit:
    def __init__(self, spec: EnvSpec, cap: float):
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError("cap must be a positive finite number")
        self.spec = spec
        self.dir = spec.evidence_dir
        self._reset_evidence()
        self.claude = Claude(ROOT, self.dir / "api_calls.jsonl", spec.env_id, env_cap=cap)
        self.rows: dict[int, dict] = {}
        self.ref: dict[int, str] = {}
        self.orig: dict[str, float] = {}
        self.cur: dict[str, float] = {}
        self.benign: list[dict] = []
        self.attempts: list[dict] = []
        self.verdicts: dict[tuple[int, str], dict] = {}
        self.exploit_class: dict[str, str] = {}
        self.iterations: list[dict] = []
        self.patched = False
        self.rules: str | None = None
        self.target = "original"
        self.dataset_size: int | None = None
        self.stop_reason = ""

    # ------------------------------------------------------------ bookkeeping

    def log(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {self.spec.env_id}: {message}"
        print(line, flush=True)
        with open(self.dir / "loop.log", "a") as handle:
            handle.write(line + "\n")

    def _reset_evidence(self) -> None:
        """Archive previous evidence and its matching patch; retain the install log."""
        self.dir.mkdir(parents=True, exist_ok=True)
        old = [p for p in self.dir.iterdir() if p.name != "install.log"]
        if old or self.spec.patch_dir.exists():
            archive = ROOT / "results" / "discarded" / self.spec.env_id / str(time.time_ns())
            archive.mkdir(parents=True)
            for p in old:
                shutil.move(str(p), str(archive / p.name))
            if self.spec.patch_dir.exists():
                shutil.move(str(self.spec.patch_dir), str(archive / "accepted_patch"))
        mirror.clear_environment(self.spec.env_id)
        mirror.record_environment(self.spec.env_id, source="hub", title=self.spec.env_id, status="running")

    def retry(self, label, operation):
        for attempt in range(MAX_TRIES):
            try:
                return operation()
            except BudgetExceeded:
                raise
            except Exception:
                self.log(f"{label} failed ({attempt + 1}/{MAX_TRIES})")
                if attempt + 1 == MAX_TRIES:
                    raise

    def ensure_rows(self, indices, *, sources=False) -> dict:
        missing = sorted(set(indices) - set(self.rows))
        if not missing and not sources:
            return {}

        def inspect():
            info = scoring.inspect_env(self.spec, sorted(set(indices)) if sources else missing, sources=sources)
            if info["dataset_size"] != self.dataset_size:
                raise AuditError("dataset size changed during inspection")
            for i in indices if sources else missing:
                row = info["rows"][str(i)]
                if row.get("gold") is None or not row.get("digest"):
                    raise AuditError(f"example {i} has no ground truth or digest")
                if i in self.rows and row["digest"] != self.rows[i]["digest"]:
                    raise AuditError(f"example {i} changed during inspection")
            return info

        info = self.retry("row inspection", inspect)
        for i, row in info["rows"].items():
            self.rows[int(i)] = row
            self.ref[int(i)] = self.spec.reference(row["gold"])
        return info

    def score_into(self, pairs, patch_dir: Path | None, store: dict) -> dict:
        pairs = list(dict.fromkeys(pairs))

        def score():
            out = scoring.score(self.spec, pairs, patch_dir)
            if out.get("integrity"):
                raise AuditError("installed package integrity check failed")
            if out.get("dataset_size") != self.dataset_size:
                raise AuditError("scoring changed the dataset size")
            values = {}
            for i, text in pairs:
                if out["digests"].get(str(i)) != self.rows[i]["digest"]:
                    raise AuditError(f"scoring changed example {i}")
                value = scoring.reward_of(out, i, text, strict=patch_dir is not None)
                if not math.isfinite(value):
                    raise AuditError(f"non-finite reward for example {i}")
                if patch_dir is None and text == self.ref[i] and value <= 0:
                    raise AuditError(f"reference for example {i} does not earn positive reward")
                values[key(i, text)] = value
            return out, values

        out, values = self.retry("patched scoring" if patch_dir else "original scoring", score)
        store.update(values)
        return out

    def ref_reward(self, i: int) -> float:
        return self.orig[key(i, self.ref[i])]

    def passes(self, rewards: dict, i: int, text: str) -> bool:
        return rewards[key(i, text)] >= ck.HIGH_FRAC * self.ref_reward(i)

    def low(self, rewards: dict, i: int, text: str) -> bool:
        drop = self.orig[key(i, text)] - rewards[key(i, text)]
        return not self.passes(rewards, i, text) and drop >= ck.LOW_FRAC * self.ref_reward(i)

    def record(self, i: int, text: str) -> dict:
        return {"example_index": i, "example_digest": self.rows[i]["digest"],
                "completion": text, "reference_completion": self.ref[i]}

    def all_pairs(self) -> list[tuple[int, str]]:
        return list(dict.fromkeys(
            (row["example_index"], row[field])
            for row in self.attempts + self.benign
            for field in ("completion", "reference_completion")
        ))

    # ------------------------------------------------------------ verification

    def verify(self, iteration: int, items: list[tuple[int, str]]) -> list[dict]:
        """Cache one verdict per pair; never turn a missing judgment into a verdict."""
        pending = {}
        for i, text in items:
            pair = (i, text.strip())
            if pair in self.verdicts or pair in pending:
                continue
            if text.strip() == self.ref[i].strip():
                verdict, reason = "correct", "matches the ground-truth reference"
            else:
                verdict, reason = strict_verdict(self.spec, text, self.rows[i]["gold"], self.rows[i].get("info"))
            if verdict in ("correct", "incorrect"):
                self.verdicts[pair] = {"verdict": verdict, "reason": reason, "method": "strict"}
            else:
                pending[pair] = {"id": len(pending), "messages": self.rows[i]["messages"],
                                 "gold": self.rows[i]["gold"], "completion": text, "strict_reason": reason}
        for attempt in range(MAX_TRIES):
            if not pending:
                break
            try:
                judged = roles.judge(self.claude, self.spec, iteration, list(pending.values()))
            except BudgetExceeded:
                raise
            except Exception:
                judged = {}
            for pair, item in list(pending.items()):
                value = judged.get(item["id"])
                if (isinstance(value, (list, tuple)) and len(value) == 2
                        and value[0] in ("correct", "incorrect") and isinstance(value[1], str) and value[1].strip()):
                    self.verdicts[pair] = {"verdict": value[0], "reason": value[1], "method": "claude"}
                    del pending[pair]
            if pending:
                self.log(f"verifier left {len(pending)} unresolved ({attempt + 1}/{MAX_TRIES})")
        if pending:
            raise AuditError(f"verifier could not judge {len(pending)} responses after two tries")
        return [dict(self.verdicts[(i, text.strip())]) for i, text in items]

    # ------------------------------------------------------------ setup

    def setup(self) -> None:
        def inspect_size():
            size = scoring.inspect_env(self.spec, [])["dataset_size"]
            if not ck.is_int(size) or size < ck.MIN_GROUND_TRUTH_EXAMPLES:
                raise AuditError("dataset is too small for the ground-truth gate")
            return size

        self.dataset_size = self.retry("environment loading", inspect_size)
        truth = spread(self.dataset_size, N_GROUND_TRUTH)
        self.probe_indices = [truth[j] for j in spread(len(truth), N_PROBE_POOL)]
        sampled = random.Random(self.spec.env_id).sample(range(self.dataset_size), min(self.dataset_size, N_SOLVER_POOL + len(truth)))
        # Prefer different examples, so exact-reference model answers remain distinct records.
        solver = ([i for i in sampled if i not in truth] + [i for i in sampled if i in truth])[:N_SOLVER_POOL]
        info = self.ensure_rows(truth + solver, sources=True)
        sources = info.get("sources") or {}
        for relative in EXTRA_SOURCES.get(self.spec.env_id, []):
            for path in sorted((ROOT / self.spec.venv / "lib").glob(f"python*/site-packages/{relative}")):
                sources[relative] = path.read_text()[:40000]
        sources = {p: s for p, s in sources.items() if not p.endswith("multiturn_env.py")}
        if not sources:
            raise AuditError("no grader source was available for the prober")
        write_json(self.dir / "inspection.json", info)
        self.context = roles.env_context(self.spec, sources)
        self.probe_context = self.context + "\n\n" + roles.examples_context([
            {**self.rows[i], "index": i, "reference": self.ref[i]} for i in self.probe_indices
        ])
        self.score_into([(i, self.ref[i]) for i in self.rows], None, self.orig)
        for i in truth:
            self.benign.append({**self.record(i, self.ref[i]), "source": "ground_truth"})
            self.verdicts[(i, self.ref[i].strip())] = {
                "verdict": "correct", "reason": "ground-truth reference", "method": "reference"}
        seen = {key(b["example_index"], b["completion"]) for b in self.benign}
        for start in range(0, len(solver), SOLVER_BATCH):
            indices = solver[start:start + SOLVER_BATCH]

            def solve():
                answers = roles.solve(self.claude, [{"id": i, "messages": self.rows[i]["messages"]} for i in indices])
                if not answers or any(i not in indices or not isinstance(t, str) for i, t in answers.items()):
                    raise AuditError("solver returned no usable responses")
                return answers

            answers = self.retry("solver", solve)
            pairs = list(answers.items())
            append_jsonl(self.dir / "solver.jsonl", {"responses": answers})
            verdicts = self.verify(0, pairs)
            self.score_into(pairs, None, self.orig)
            for (i, text), judge in zip(pairs, verdicts):
                if judge["verdict"] == "correct" and key(i, text) not in seen:
                    self.benign.append({**self.record(i, text), "source": "model", "judge": judge})
                    seen.add(key(i, text))
            if sum(b["source"] == "model" for b in self.benign) >= MIN_MODEL:
                break
        for row in self.benign:
            append_jsonl(self.dir / "benign.jsonl", row)
        if len(self.benign) < ck.MIN_BENIGN_RECORDS:
            raise AuditError("not enough distinct benign completions")
        self.cur = dict(self.orig)
        self.log(f"setup: {len(truth)} ground-truth and {len(self.benign) - len(truth)} verified model records")

    # ------------------------------------------------------------ probe / repair

    def case_context(self, row: dict) -> dict:
        i, text = row["example_index"], row["completion"]
        return {**row, "gold": self.rows[i]["gold"], "original": self.orig[key(i, text)],
                "current": self.cur[key(i, text)], "reference": self.ref_reward(i),
                "verdict": row["judge"]["verdict"]}

    def probe(self, iteration: int) -> list[dict]:
        def propose():
            result = roles.probe(
                self.claude, self.spec, self.probe_context, iteration,
                (self.spec.patch_dir / "patch.py").read_text() if self.patched else None,
                {i: self.cur[key(i, self.ref[i])] for i in self.probe_indices},
                [self.case_context(a) for a in self.attempts],
            )
            append_jsonl(self.dir / "proposals.jsonl", {"iteration": iteration, "text": result.text, "data": result.data})
            proposals = result.data.get("proposals") if isinstance(result.data, dict) else None
            if not isinstance(proposals, list) or len(proposals) != 3:
                raise AuditError("prober must return exactly three candidates")
            for p in proposals:
                if (not isinstance(p, dict) or not ck.is_int(p.get("example_index"))
                        or p["example_index"] not in self.probe_indices
                        or p.get("exploit_class") not in EXPLOIT_CLASSES
                        or not isinstance(p.get("completion"), str)
                        or any(not isinstance(p.get(f), str) or not p[f].strip()
                               for f in ("mechanism_id", "mechanism", "why_incorrect"))):
                    raise AuditError("prober returned an invalid candidate")
            return proposals

        proposals = self.retry("prober", propose)
        pairs = [(p["example_index"], p["completion"]) for p in proposals]
        scoring_pairs = pairs + [(i, self.ref[i]) for i, _ in pairs]
        self.score_into(scoring_pairs, None, self.orig)
        if self.patched:
            self.score_into(scoring_pairs, self.spec.patch_dir, self.cur)
        else:
            self.cur.update(self.orig)
        verdicts = self.verify(iteration, pairs)
        added = []
        for p, judge in zip(proposals, verdicts):
            i, text = p["example_index"], p["completion"]
            exploit_id = None
            if judge["verdict"] == "incorrect" and self.passes(self.orig, i, text):
                slug = re.sub(r"[^a-z0-9]+", "-", p["mechanism_id"].lower()).strip("-")[:48] or "exploit"
                exploit_id = f"{slug}-{ck.digest(p['mechanism_id'])[:10]}"
                self.exploit_class.setdefault(exploit_id, p["exploit_class"])
            row = {**p, **self.record(i, text), "attempt_id": f"attempt-{len(self.attempts) + 1:04d}",
                   "iteration": iteration, "judge": judge, "exploit_id": exploit_id}
            if exploit_id:
                row["exploit_class"] = self.exploit_class[exploit_id]
            self.attempts.append(row)
            added.append(row)
            append_jsonl(self.dir / "attempts.jsonl", row)
        self.write_replays()
        self.log(f"iteration {iteration}: {len(added)} attempts, {len(self.exploit_class)} confirmed mechanisms total")
        return added

    def write_replays(self) -> None:
        for exploit_id, exploit_class in self.exploit_class.items():
            cases = [a for a in self.attempts if a["exploit_id"] == exploit_id]
            path = self.dir / "replays" / f"{exploit_id}.json"
            write_json(path, {"env_id": self.spec.env_id, "exploit_id": exploit_id,
                              "exploit_class": exploit_class, "cases": cases})
            first = cases[0]
            mirror.record_exploit(
                self.spec.env_id, exploit_id, exploit_class=exploit_class, iteration=first["iteration"],
                summary=first["mechanism"][:200], sample_completion=first["completion"],
                reward_original=self.orig[key(first["example_index"], first["completion"])],
                evidence_path=path.relative_to(ROOT).as_posix(),
            )

    def gate_problems(self, rewards: dict) -> list[str]:
        problems = []
        for a in self.attempts:
            if a["exploit_id"] and not self.low(rewards, a["example_index"], a["completion"]):
                problems.append(f"{a['attempt_id']} still fails the LOW gate")
        for i, _ in self.all_pairs():
            if not self.passes(rewards, i, self.ref[i]):
                problems.append(f"reference for example {i} no longer passes")
        kept = sum(self.passes(rewards, b["example_index"], b["completion"]) for b in self.benign)
        if kept < ck.BENIGN_GATE * len(self.benign):
            problems.append(f"benign retention {kept}/{len(self.benign)} is below 90%")
        models = [b for b in self.benign if b["source"] == "model"]
        if len(models) < MIN_MODEL:
            problems.append(f"need at least {MIN_MODEL} distinct verified model records")
        passing = [b for b in models if self.passes(self.orig, b["example_index"], b["completion"])]
        kept = sum(self.passes(rewards, b["example_index"], b["completion"]) for b in passing)
        if kept < ck.BENIGN_GATE * len(passing):
            problems.append(f"model retention {kept}/{len(passing)} is below 90%")
        return list(dict.fromkeys(problems))

    def repair(self, iteration: int) -> str | None:
        cases = [self.case_context(a) for a in self.attempts if a["exploit_id"]]
        opened = [a for a in cases if not self.low(self.cur, a["example_index"], a["completion"])]
        closed = [a for a in cases if a not in opened]
        feedback = None
        if sum(b["source"] == "model" for b in self.benign) < MIN_MODEL:
            self.log("repair skipped: insufficient verified model records for the solver gate")
            return None
        for attempt in range(1, MAX_TRIES + 1):
            try:
                result = roles.repair(
                    self.claude, self.spec, self.context, patching.template_for_prompt(self.spec), iteration,
                    opened, closed, [{**b, "gold": self.rows[b["example_index"]]["gold"]} for b in self.benign],
                    self.rules, feedback,
                )
                data = result.data if isinstance(result.data, dict) else {}
                append_jsonl(self.dir / "repairs.jsonl", {"iteration": iteration, "try": attempt,
                                                         "text": result.text, "data": result.data})
                if not isinstance(data.get("code"), str) or not isinstance(data.get("summary"), str):
                    raise AuditError("repairer returned no code and summary")
                problems = patching.static_problems(self.spec, data["code"], cases)
                if not problems:
                    with tempfile.TemporaryDirectory(prefix="audit-candidate-") as tmp:
                        candidate = patching.write_candidate(self.spec, data["code"], data["summary"], Path(tmp) / "patch")
                        rewards = {}
                        self.score_into(self.all_pairs(), candidate, rewards)
                        problems = self.gate_problems(rewards)
                        if not problems:
                            digest = patching.install(candidate, self.spec)
                            self.patched, self.rules, self.cur = True, data["code"], rewards
                            self.log(f"iteration {iteration}: accepted repair {attempt}")
                            return digest
                feedback = "\n".join(problems)
            except BudgetExceeded:
                raise
            except Exception as exc:
                feedback = f"{type(exc).__name__}: {exc}"
            append_jsonl(self.dir / "repair_rejections.jsonl", {"iteration": iteration, "try": attempt, "reason": feedback})
            self.log(f"iteration {iteration}: rejected repair {attempt}/{MAX_TRIES}")
        return None

    # ------------------------------------------------------------ completion

    def invariants(self) -> list[str]:
        pending = []
        for exploit_id, exploit_class in self.exploit_class.items():
            cases = [a for a in self.attempts if a["exploit_id"] == exploit_id]
            first = cases[0]
            i, text = first["example_index"], first["completion"]
            if self.patched and all(self.low(self.cur, a["example_index"], a["completion"]) for a in cases):
                mirror.mark_exploit_patched(self.spec.env_id, exploit_id, reward_patched=self.cur[key(i, text)])
            evidence = {
                "env_id": self.spec.env_id, "exploit_id": exploit_id,
                "evidence_path": (self.dir / "replays" / f"{exploit_id}.json").relative_to(ROOT).as_posix(),
                "task": self.spec.task, "reward": self.spec.reward, "mechanism": first["mechanism"],
                "why_incorrect": first["judge"]["reason"], "sample": text,
                "reward_original": self.orig[key(i, text)], "reward_reference": self.ref_reward(i),
                "reward_patched": self.cur[key(i, text)] if self.patched else None, "rules": self.rules,
            }

            def extract():
                inv = extract_invariant(evidence, exploit_class=exploit_class, claude=self.claude, iteration=first["iteration"])
                if inv is None:
                    raise AuditError("invariant extraction returned no result")
                mirror.record_invariant(inv)

            try:
                self.retry("invariant extraction", extract)
            except Exception as exc:
                pending.append(exploit_id)
                append_jsonl(self.dir / "invariant_errors.jsonl", {"exploit_id": exploit_id, "reason": f"{type(exc).__name__}: {exc}"})
        return pending

    def finish(self) -> dict:
        if not self.exploit_class:
            incorrect = {a["completion"].strip() for a in self.attempts if a["judge"]["verdict"] == "incorrect" and a["completion"].strip()}
            if len(incorrect) < ck.MIN_ROBUST_ATTEMPTS:
                raise AuditError("too few distinct incorrect attempts to claim robustness")
        write_json(self.dir / "runtime.json", self.spec.runtime(self.patched))
        built = self.retry("final evidence scoring", lambda: leaderboard.derive_status(ROOT, self.spec.env_id, self.dir))
        pending = self.invariants()
        entry = built["entry"]
        entry["cost_usd"] = round(sum(c["cost_usd"] for c in read_jsonl(self.dir / "api_calls.jsonl")), 4)
        mirror.record_environment(self.spec.env_id, source="hub", title=self.spec.env_id, status=entry["status"])
        summary = {**built, "stop_reason": self.stop_reason, "pending_invariants": pending}
        write_json(self.dir / "summary.json", summary)
        self.log(f"{entry['status']}: {entry['iterations']} iterations, cost ${entry['cost_usd']:.4f}; {len(pending)} pending invariants")
        return summary

    def run(self) -> dict:
        try:
            self.setup()
            for iteration in range(1, MAX_ITER + 1):
                try:
                    added = self.probe(iteration)
                except BudgetExceeded:
                    # Only completed iterations can be published. A paid, incomplete probe
                    # remains failure evidence; it cannot masquerade as a failed attack.
                    calls = read_jsonl(self.dir / "api_calls.jsonl")
                    if not self.iterations or any(c["iteration"] > len(self.iterations) for c in calls):
                        raise
                    self.stop_reason = "budget exhausted before the next probe"
                    break
                row = {"iteration": iteration, "target": self.target, "patch_after": None}
                open_cases = [a for a in self.attempts if a["exploit_id"] and not self.low(self.cur, a["example_index"], a["completion"])]
                budget_stop = False
                if open_cases:
                    try:
                        row["patch_after"] = self.repair(iteration)
                    except BudgetExceeded:
                        self.stop_reason = "budget exhausted during repair"
                        budget_stop = True
                self.target = row["patch_after"] or self.target
                self.iterations.append(row)
                append_jsonl(self.dir / "iterations.jsonl", row)
                if budget_stop:
                    break
                incorrect = {a["completion"].strip() for a in self.attempts if a["judge"]["verdict"] == "incorrect" and a["completion"].strip()}
                no_success = not any(a["judge"]["verdict"] == "incorrect" and self.passes(self.cur, a["example_index"], a["completion"]) for a in added)
                if (row["patch_after"] is None and not open_cases and no_success
                        and (self.exploit_class or len(incorrect) >= ck.MIN_ROBUST_ATTEMPTS)):
                    self.stop_reason = "no successful attack on the current grader"
                    break
            else:
                self.stop_reason = "iteration limit reached"
            return self.finish()
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            (self.dir / "runtime.json").unlink(missing_ok=True)
            write_json(self.dir / "failed.json", {"reason": reason})
            mirror.record_environment(self.spec.env_id, source="hub", title=self.spec.env_id, status="failed_to_run")
            self.log("failed to complete; see failed.json")
            result = {"entry": leaderboard.failed_entry(ROOT, self.spec.env_id, self.dir, reason)}
            write_json(self.dir / "summary.json", result)
            return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("env_id", help="selected owner/name from envs.yaml")
    parser.add_argument("--cap", type=float, default=2.3, help="per-run API spend cap in USD (default: 2.3)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.cap) or args.cap <= 0:
        parser.error("--cap must be a positive finite number")
    specs, _ = load_envs()
    if args.env_id not in specs:
        parser.error(f"unknown selected environment: {args.env_id}")
    summary = Audit(specs[args.env_id], args.cap).run()
    return int(summary["entry"]["status"] == "failed_to_run" or bool(summary.get("pending_invariants")))


if __name__ == "__main__":
    sys.exit(main())

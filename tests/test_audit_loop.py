"""Offline orchestration tests, validated against the frozen acceptance checker.

    .venvs/hub/bin/python -m unittest discover -s tests -p test_audit_loop.py -v
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from harden.audit import common, leaderboard, loop, patching, scoring
from harden.audit.llm import BudgetExceeded, Result
from harden.store import mirror

GOOD_RULES = '''import re

def tighten(text, gold, info, reward):
    answers = re.findall(r"<reversed_text>(.*?)</reversed_text>", text, re.S)
    return reward if answers and all(a.strip() == gold for a in answers) else 0.0
'''


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('harden.store.moss_retrieval.require_moss_config', return_value=None))
        self.stack.enter_context(patch('harden.store.moss_retrieval.retrieve_context', return_value=SimpleNamespace(text='[]', receipt={'backend':'moss-test'}, offered_ids=())))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="audit-loop-test-")))
        self.spec = replace(common.load_envs()[0]["primeintellect/reverse-text"], dataset_size=100)
        interpreter = self.root / self.spec.python
        interpreter.parent.mkdir(parents=True)
        interpreter.touch()
        for module in (loop, scoring, patching):
            self.stack.enter_context(patch.object(module, "ROOT", self.root))
        self.stack.enter_context(patch.object(common, "EVIDENCE", self.root / "results/evidence"))
        self.stack.enter_context(patch.object(common, "PATCHES", self.root / "patches"))
        self.stack.enter_context(patch.object(mirror, "DB_PATH", self.root / "invariants.db"))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.mode = "patched"
        self.repair_codes = []
        self.n_inspect = self.n_probe = self.n_repair = self.n_judge = self.n_extract = 0
        self.inspect_failures = 0
        self.cap_after_patch = False
        self.fail_extract = False
        self.model_prefix = "Reasoning.\n"
        self.fake_errors = False
        self.changed_rows = False
        self.original_error = False
        self.real_inspect, self.real_worker = scoring.inspect_env, common.ck.run_worker
        self.stack.enter_context(patch.object(scoring, "inspect_env", self.inspect))
        self.stack.enter_context(patch.object(common.ck, "run_worker", self.worker))

        class Client:
            def __init__(self, root, calls_path, env_id, env_cap):
                self.calls_path = calls_path
                self.spent = 0
                self.env_cap = env_cap

        self.stack.enter_context(patch.object(loop, "Claude", Client))
        self.stack.enter_context(patch.object(loop.roles, "solve", self.solve))
        self.stack.enter_context(patch.object(loop.roles, "probe", self.probe))
        self.stack.enter_context(patch.object(loop.roles, "repair", self.repair))
        self.stack.enter_context(patch.object(loop.roles, "judge", self.judge))
        self.stack.enter_context(patch.object(loop, "extract_invariant", self.extract))

    def ref(self, i):
        return self.spec.reference(f"gold-{i}")

    def inspect(self, spec, indices, sources=False):
        self.n_inspect += 1
        if self.inspect_failures:
            self.inspect_failures -= 1
            raise scoring.ScoringError("fixture loader failure")
        return {"dataset_size": 100, "rows": {str(i): {
            "digest": f"digest-{i}", "messages": [{"role": "user", "content": f"task-{i}"}],
            "gold": f"gold-{i}", "info": {},
        } for i in indices}, "sources": {"fixture.py": "def reward(text, gold): return float(gold in text)"} if sources else {}}

    def worker(self, root, python, mode, runtime, items, indices):
        namespace = {}
        if mode == "patched":
            source = (root / runtime["patch"]).read_text().split(patching.RULES_END)[0]
            # Only test-authored rules execute here; production uses the isolated worker.
            exec(source, namespace)
        rewards = {}
        for item in items:
            i, text = item["example_index"], item["completion"]
            value = float(self.ref(i) in text)
            if mode == "patched":
                value = namespace["tighten"](text, f"gold-{i}", {}, value)
            error = "fixture reward error" if (mode == "patched" and self.fake_errors) or (mode == "original" and self.original_error and text.startswith("wrong")) else None
            rewards[item["key"]] = {"reward": None if error else value, "error": error}
        return {"rewards": rewards, "digests": {str(i): f"digest-{i}" + ("-changed" if mode == "patched" and self.changed_rows else "") for i in indices},
                "dataset_size": 100, "integrity": [], "fingerprint": "fixture", "dists": []}

    def call(self, client, iteration, role):
        client.spent += 0.01
        common.append_jsonl(client.calls_path, {"iteration": iteration, "role": role, "cost_usd": 0.01})

    def solve(self, client, tasks):
        self.call(client, 0, "solver")
        return {t["id"]: self.model_prefix + self.ref(t["id"]) for t in tasks}

    def probe(self, client, spec, context, iteration, target, reference_scores, history):
        self.n_probe += 1
        if self.cap_after_patch and iteration > 1:
            raise BudgetExceeded("fixture cap before probe")
        self.call(client, iteration, "prober")
        proposals = []
        for n, i in enumerate(sorted(reference_scores)[:3]):
            if self.mode == "correct":
                text = self.ref(i)
            elif self.mode == "patched" and iteration == 1 or self.mode == "unpatched":
                text = self.ref(i) + f"<reversed_text>wrong-{n}</reversed_text>"
            else:
                text = f"wrong-{iteration}-{n}"
            proposals.append({"example_index": i, "completion": text,
                              "exploit_class": next(iter(common.EXPLOIT_CLASSES)),
                              "mechanism_id": "../../multiple-answers", "mechanism": "The parser accepts the first answer.",
                              "why_incorrect": "The response offers two different final answers."})
        return Result("prober", json.dumps(proposals), {"proposals": proposals}, "end_turn", None, .01, "fixture")

    def repair(self, client, spec, context, template, iteration, opened, closed, benign, rules, feedback):
        self.n_repair += 1
        self.call(client, iteration, "repairer")
        code = self.repair_codes.pop(0) if self.repair_codes else GOOD_RULES
        return Result("repairer", code, {"code": code, "summary": "Require one consistent correct final answer."}, "end_turn", None, .01, "fixture")

    def judge(self, client, spec, iteration, items):
        self.n_judge += 1
        self.call(client, iteration, "verifier")
        return {i["id"]: ("incorrect", "The answer contradicts the ground truth.") for i in items}

    def extract(self, evidence, *, exploit_class, claude, iteration):
        self.n_extract += 1
        self.call(claude, iteration, "summarizer")
        if self.fail_extract:
            return None
        return mirror.Invariant(
            evidence["env_id"], evidence["exploit_id"], "Ambiguous answers",
            "The parser accepts one answer among conflicting answers.",
            "The parser checks only a fragment of the final response.",
            "Applies when the grader extracts one answer from many.",
            "Reject conflicting final answers while preserving a single correct answer.", evidence["evidence_path"],
        )

    def run_audit(self):
        audit = loop.Audit(self.spec, 2.3)
        return audit, audit.run()

    def check_entry(self, summary):
        entry = summary["entry"]
        rep = common.ck.Report()
        common.ck.check_entry_fields(entry, self.spec.env_id, rep)
        if entry["status"] == "failed_to_run":
            common.ck.check_failed_entry(entry, self.root, rep)
            self.assertFalse((self.spec.evidence_dir / "runtime.json").exists())
        else:
            rep.extend(common.ck.evaluate_entry(entry, self.root, self.spec.env_id))
            common.ck.check_invariants(self.root, [entry], rep)
        self.assertEqual(rep.failures, [])
        if entry["status"] != "failed_to_run":
            rebuilt = leaderboard.derive_status(self.root, self.spec.env_id, self.spec.evidence_dir)
            self.assertEqual(rebuilt["entry"], entry)

    def test_patch_is_reprobed_and_evidence_passes_checker(self):
        audit, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "patched")
        self.assertEqual(result["entry"]["iterations"], 2)
        self.assertEqual(len(result["entry"]["exploits"]), 1)
        self.assertEqual(len(mirror.invariant_rows(self.spec.env_id)), 1)
        self.assertNotIn("..", result["entry"]["exploits"][0]["exploit_id"])
        self.assertEqual(audit.iterations[1]["target"], audit.iterations[0]["patch_after"])
        self.assertIsNone(audit.iterations[1]["patch_after"])
        self.check_entry(result)

    def test_robust_and_original_errors_count_as_zero(self):
        self.mode, self.original_error = "robust", True
        _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "robust")
        self.assertEqual(result["entry"]["iterations"], 1)
        self.assertEqual(self.n_repair, 0)
        self.check_entry(result)

    def test_rejected_repairs_leave_unpatched_after_five_iterations(self):
        self.mode = "unpatched"
        self.repair_codes = ["def tighten(text, gold, info, reward): return 0.0"] * 10
        audit, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "unpatched")
        self.assertEqual(result["entry"]["iterations"], 5)
        self.assertFalse(audit.patched)
        self.assertEqual(self.n_repair, 10)
        replay = json.loads(next((self.spec.evidence_dir / "replays").glob("*.json")).read_text())
        self.assertEqual(len(replay["cases"]), 15)
        self.check_entry(result)

    def test_repair_retries_after_model_retention_failure(self):
        self.repair_codes = [GOOD_RULES.replace("return reward if", "return reward if not text.startswith('Reasoning.') and")]
        _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "patched")
        self.assertEqual(self.n_repair, 2)
        reasons = common.read_jsonl(self.spec.evidence_dir / "repair_rejections.jsonl")
        self.assertIn("model retention", reasons[0]["reason"])
        self.check_entry(result)

    def test_static_failure_retried_before_scoring(self):
        self.repair_codes = ["def tighten(:"]
        _, result = self.run_audit()
        self.assertEqual(self.n_repair, 2)
        self.assertEqual(result["entry"]["status"], "patched")
        self.check_entry(result)

    def test_changed_dataset_and_patched_reward_errors_are_rejected(self):
        for flag in ("fake_errors", "changed_rows"):
            with self.subTest(flag=flag):
                setattr(self, flag, True)
                self.mode = "unpatched"
                _, result = self.run_audit()
                self.assertEqual(result["entry"]["status"], "unpatched")
                self.assertFalse(self.spec.patch_dir.exists())
                self.check_entry(result)
                setattr(self, flag, False)

    def test_failed_load_retries_twice_and_writes_failure_evidence(self):
        self.inspect_failures = 2
        _, result = self.run_audit()
        self.assertEqual(self.n_inspect, 2)
        self.assertEqual(result["entry"]["status"], "failed_to_run")
        self.check_entry(result)

    def test_transient_load_failure_recovers(self):
        self.inspect_failures = 1
        _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "patched")
        self.check_entry(result)

    def test_budget_after_patch_is_unpatched_without_claiming_a_final_probe(self):
        self.cap_after_patch = True
        _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "unpatched")
        self.assertEqual(result["entry"]["iterations"], 1)
        self.assertIn("budget", result["stop_reason"])
        self.check_entry(result)

    def test_budget_during_repair_preserves_confirmed_exploits(self):
        def stop(*args, **kwargs):
            raise BudgetExceeded("fixture cap during repair")
        with patch.object(loop.roles, "repair", stop):
            _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "unpatched")
        self.assertEqual(result["entry"]["iterations"], 1)
        self.check_entry(result)

    def test_budget_after_a_paid_probe_keeps_incomplete_iteration_as_failure(self):
        strict = loop.strict_verdict
        def uncertain_attack(spec, text, gold, info):
            if text.count("<reversed_text>") > 1:
                return "uncertain", "needs independent judgment"
            return strict(spec, text, gold, info)
        def exhausted(*args, **kwargs):
            raise BudgetExceeded("fixture cap before verifier")
        with patch.object(loop, "strict_verdict", uncertain_attack), patch.object(loop.roles, "judge", exhausted):
            _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "failed_to_run")
        self.assertEqual(result["entry"]["iterations"], 1)
        self.assertEqual(len(common.read_jsonl(self.spec.evidence_dir / "proposals.jsonl")), 1)
        self.assertFalse((self.spec.evidence_dir / "runtime.json").exists())
        self.check_entry(result)

    def test_unresolved_verifier_is_failure_not_incorrect_or_robust(self):
        def missing(client, spec, iteration, items):
            self.n_judge += 1
            self.call(client, iteration, "verifier")
            return {}
        with patch.object(loop, "strict_verdict", return_value=("uncertain", "needs judgment")), patch.object(loop.roles, "judge", missing):
            _, result = self.run_audit()
        self.assertEqual(self.n_judge, 2)
        self.assertEqual(result["entry"]["status"], "failed_to_run")
        self.check_entry(result)

    def test_verifier_caches_normalized_pairs_and_retries_only_missing_ids(self):
        audit = loop.Audit(self.spec, 2.3)
        audit.dataset_size = 100
        audit.ensure_rows([1, 2])
        batches = []
        def partial(client, spec, iteration, items):
            batches.append([i["id"] for i in items])
            return {items[0]["id"]: ("incorrect", "Not the correct answer.")}
        with patch.object(loop, "strict_verdict", return_value=("uncertain", "needs judgment")), patch.object(loop.roles, "judge", partial):
            first = audit.verify(1, [(1, "ambiguous"), (1, " ambiguous "), (2, "ambiguous")])
            second = audit.verify(2, [(1, "ambiguous")])
        self.assertEqual(batches, [[0, 1], [1]])
        self.assertEqual(first[0], first[1])
        self.assertEqual(first[0], second[0])

    def test_correct_probes_never_claim_robustness(self):
        self.mode = "correct"
        _, result = self.run_audit()
        self.assertEqual(self.n_probe, 5)
        self.assertEqual(result["entry"]["status"], "failed_to_run")
        self.check_entry(result)

    def test_pending_invariants_are_explicit_and_reconcilable(self):
        self.fail_extract = True
        _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "patched")
        self.assertEqual(len(result["pending_invariants"]), 1)
        self.assertEqual(self.n_extract, 2)
        self.assertTrue((self.spec.evidence_dir / "invariant_errors.jsonl").is_file())
        self.assertEqual(len(mirror.exploit_rows(self.spec.env_id)), 1)

    def test_rerun_archives_evidence_and_matching_patch_without_losing_install_log(self):
        self.run_audit()
        (self.spec.evidence_dir / "install.log").write_text("installed")
        loop.Audit(self.spec, 2.3)
        archive = list((self.root / "results/discarded" / self.spec.env_id).iterdir())
        self.assertEqual(len(archive), 1)
        self.assertTrue((archive[0] / "accepted_patch/patch.py").is_file())
        self.assertTrue((archive[0] / "summary.json").is_file())
        self.assertEqual((self.spec.evidence_dir / "install.log").read_text(), "installed")
        self.assertEqual(mirror.invariant_rows(self.spec.env_id), [])

    def test_fifth_iteration_repair_does_not_start_a_sixth_probe(self):
        self.mode = "unpatched"
        self.repair_codes = ["def tighten(text, gold, info, reward): return 0.0"] * 8
        _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "patched")
        self.assertEqual(result["entry"]["iterations"], 5)
        self.assertEqual(self.n_probe, 5)
        self.check_entry(result)

    def test_failed_prober_calls_are_preserved_as_failure_costs(self):
        def malformed(client, spec, context, iteration, target, reference_scores, history):
            self.n_probe += 1
            self.call(client, iteration, "prober")
            return Result("prober", "bad JSON", None, "end_turn", None, .01, "fixture")
        with patch.object(loop.roles, "probe", malformed):
            _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "failed_to_run")
        self.assertEqual(self.n_probe, 2)
        self.assertAlmostEqual(result["entry"]["cost_usd"], .03)
        self.assertEqual(len(common.read_jsonl(self.spec.evidence_dir / "proposals.jsonl")), 2)
        self.check_entry(result)

    def test_missing_model_baseline_prevents_patch_acceptance(self):
        with patch.object(loop.roles, "solve", side_effect=lambda client, tasks: {
            t["id"]: "wrong solver answer" for t in tasks
        }):
            _, result = self.run_audit()
        self.assertEqual(result["entry"]["status"], "unpatched")
        self.assertEqual(self.n_repair, 0)
        self.check_entry(result)

    @unittest.skipUnless(os.environ.get("AUDIT_REAL_ENV_TEST") == "1", "opt-in installed reverse-text environment")
    def test_installed_environment_end_to_end_without_api_calls(self):
        repo = common.ROOT
        for relative in ("scripts/check_leaderboard.py", "harden/audit/inspect_env.py"):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / relative, destination)
        shutil.rmtree(self.root / self.spec.venv)
        (self.root / self.spec.venv).symlink_to(repo / self.spec.venv, target_is_directory=True)
        rows = {}
        def inspect(spec, indices, sources=False):
            info = self.real_inspect(spec, indices, sources)
            rows.update({int(i): row for i, row in info["rows"].items()})
            return info
        self.ref = lambda i: self.spec.reference(rows[i]["gold"])
        def propose(client, spec, context, iteration, target, reference_scores, history):
            result = self.probe(client, spec, context, iteration, target, reference_scores, history)
            if iteration == 1:
                for p in result.data["proposals"]:
                    p["completion"] = spec.reference(rows[p["example_index"]]["gold"] + "!")
                    p["mechanism_id"] = "near-match-credit"
                    p["mechanism"] = "A near-match receives high similarity credit without being an exact reversal."
                    p["why_incorrect"] = "The final reversed text contains an extra character."
            return result
        with patch.object(scoring, "inspect_env", inspect), patch.object(common.ck, "run_worker", self.real_worker), patch.object(loop.roles, "probe", propose):
            _, result = self.run_audit()
            self.assertEqual(result["entry"]["status"], "patched", result)
            self.assertEqual(result["entry"]["iterations"], 2)
            self.check_entry(result)

    def test_cli_validates_inputs_before_resetting_evidence(self):
        with patch.object(loop, "load_envs", return_value=({self.spec.env_id: self.spec}, [])), patch.object(loop, "Audit") as audit:
            for args in (["unknown/env"], [self.spec.env_id, "--cap", "nan"], [self.spec.env_id, "--cap", "0"]):
                with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    loop.main(args)
                self.assertEqual(caught.exception.code, 2)
            audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()

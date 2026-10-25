"""Per-environment audit loop: probe the grader, verify, tighten, repeat (at most 5 times).

    .venvs/hub/bin/python -m harden.audit.pilot_loop ENV_ID [--rounds 2]

Writes the evidence files scripts/check_leaderboard.py specifies under
results/evidence/<env_id>/, the tightened grader under patches/<env_id>/, and the
invariant rows in invariants.db. Generated responses go only into evidence files; the
console log reports counts and scores.

The pilot is bounded to two rounds by default. Partial evidence and budget stops are
reported explicitly; the full leaderboard has its own larger acceptance requirements.
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
    def __init__(self, spec: EnvSpec, cap: float | None = None):
        from harden.store.moss_retrieval import require_moss_config
        require_moss_config()
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
        out, pending = {}, []
        for ident, (index, text) in enumerate(items):
            pair = (index, text)
            if pair in self.verdicts:
                out[ident] = self.verdicts[pair]
                continue
            row = self.rows[index]
            verdict, reason = strict_verdict(self.spec, text, row['gold'], row.get('info'))
            if verdict == 'uncertain':
                pending.append({'id': ident, 'messages': row['messages'], 'gold': row['gold'],
                                'completion': text, 'strict_reason': reason})
            else:
                out[ident] = {'verdict': verdict, 'reason': reason, 'method': 'strict'}
        if pending:
            for ident, (verdict, reason) in roles.judge(self.claude, self.spec, iteration, pending).items():
                if verdict in ('correct', 'incorrect'):
                    out[ident] = {'verdict': verdict, 'reason': reason, 'method': 'model'}
        for ident, value in out.items(): self.verdicts[items[ident]] = value
        return [out.get(ident, {'verdict': 'uncertain', 'reason': 'Independent verifier returned no conclusive result'})
                for ident in range(len(items))]

    def flush(self):
        for name, rows in [('attempts', self.attempts), ('benign', self.benign), ('iterations', self.iterations)]:
            (self.dir / f'{name}.jsonl').write_text(''.join(__import__('json').dumps(row) + '\n' for row in rows))
        runtime = self.spec.runtime(self.patched)
        write_json(self.dir / 'runtime.json', runtime)
        grouped = {}
        for attempt in self.attempts:
            if attempt.get('exploit_id'): grouped.setdefault(attempt['exploit_id'], []).append(attempt)
        replay_dir = self.dir / 'replays'; replay_dir.mkdir(exist_ok=True)
        for exploit_id, cases in grouped.items():
            write_json(replay_dir / f'{exploit_id}.json', {'env_id': self.spec.env_id,
                'exploit_id': exploit_id, 'exploit_class': cases[0]['exploit_class'], 'cases': cases})

    def setup(self):
        size = self.spec.dataset_size
        if size < 2: raise ValueError('Dataset too small for audit')
        truth = sorted({round(i * (size - 1) / (min(N_GROUND_TRUTH, size) - 1)) for i in range(min(N_GROUND_TRUTH, size))})
        if len(truth) < ck.MIN_BENIGN_RECORDS: raise ValueError('Dataset too small for the audit benign contract')
        pool = [i for i in range(size) if i not in truth]
        random.Random(42).shuffle(pool); model_indices = pool[:N_SOLVER_POOL]
        info = scoring.inspect_env(self.spec, truth + model_indices, sources=True)
        self.dataset_size = info['dataset_size']
        for index, row in info['rows'].items():
            if row.get('gold') is None: raise ValueError('Missing gold answer; cannot establish reference correctness')
            self.rows[int(index)] = row; self.ref[int(index)] = self.spec.reference(row['gold'])
        references = [(i, self.ref[i]) for i in self.rows]
        base = self.score_into(references, None, self.orig)
        if base.get('integrity'): raise ValueError(f'Original package integrity failed: {base["integrity"]}')
        if any(self.ref_reward(i) <= 0 for i in self.rows): raise ValueError('A reference completion failed the original reward')
        for i in truth:
            self.benign.append({**self.record(i, self.ref[i]), 'source': 'ground_truth'})
        self.cur.update(self.orig)
        # Keep only grader context and a few examples, bounded for the Haiku pilot.
        sources = {name: content[:14000] for name, content in info.get('sources', {}).items()
                   if not any(skip in name for skip in SKIP_SOURCES)}
        self.context = roles.env_context(self.spec, sources)[:22000]
        examples = [{'index': i, **self.rows[i], 'reference': self.ref[i]} for i in truth[:3]]
        self.context += '\n' + roles.examples_context(examples)[:10000]
        # Retrieve other environments' evidence once per pilot, with no LLM call.
        from harden.store.moss_retrieval import retrieve_context
        retrieval = retrieve_context(self.context, self.spec.task, target_env_id=self.spec.env_id, max_chars=4000)
        write_json(self.dir / 'retrieved_knowledge.json', retrieval.receipt)
        self.context += '\nUntrusted knowledge from other environments; check applicability:\n' + retrieval.text
        self.probe_indices = truth[:3]
        self.flush()
        # Model-authored benign samples are required for an acceptance-checked patch.
        for start in range(0, len(model_indices), SOLVER_BATCH):
            if sum(row['source'] == 'model' for row in self.benign) >= MIN_MODEL: break
            indices = model_indices[start:start + SOLVER_BATCH]
            tasks = [{'id': i, 'messages': self.rows[i]['messages']} for i in indices]
            responses = roles.solve(self.claude, tasks)
            pairs = [(i, responses[i]) for i in indices if i in responses and responses[i].strip()]
            verdicts = self.verify(0, pairs)
            if pairs: self.score_into(pairs, None, self.orig)
            for (i, completion), verdict in zip(pairs, verdicts):
                if verdict['verdict'] == 'correct' and self.passes(self.orig, i, completion):
                    self.benign.append({**self.record(i, completion), 'source': 'model', 'judge': verdict})
            self.flush()
        self.cur.update(self.orig)
        if sum(row['source'] == 'model' for row in self.benign) < MIN_MODEL:
            raise ValueError('Could not establish five independently correct model benign examples within the pilot')

    def case(self, row):
        index, completion = row['example_index'], row['completion']
        return {**row, 'gold': self.rows[index]['gold'], 'original': self.orig[key(index, completion)],
                'reference': self.ref_reward(index), 'current': self.cur[key(index, completion)]}

    def record_finding(self, attempt):
        exploit_id = attempt['exploit_id']; index = attempt['example_index']
        evidence_path = (self.dir / 'replays' / f'{exploit_id}.json').relative_to(ROOT).as_posix()
        mirror.record_exploit(self.spec.env_id, exploit_id, exploit_class=attempt['exploit_class'],
            iteration=attempt['iteration'], summary=attempt['mechanism'][:200], sample_completion=attempt['completion'],
            reward_original=self.orig[key(index, attempt['completion'])], evidence_path=evidence_path)
        if mirror.invariant_rows(self.spec.env_id) and any(r['exploit_id'] == exploit_id for r in mirror.invariant_rows(self.spec.env_id)):
            return
        inv = extract_invariant({'env_id': self.spec.env_id, 'exploit_id': exploit_id, 'evidence_path': evidence_path,
            'task': self.spec.task, 'reward': self.spec.reward, 'mechanism': attempt['mechanism'],
            'why_incorrect': attempt['judge']['reason'], 'sample': attempt['completion'],
            'reward_original': self.orig[key(index, attempt['completion'])], 'reward_reference': self.ref_reward(index),
            'reward_patched': None, 'rules': self.rules}, exploit_class=attempt['exploit_class'],
            claude=self.claude, iteration=attempt['iteration'])
        if inv: mirror.record_invariant(inv)

    def run(self, rounds=2):
        import hashlib
        stopped = None
        try:
            self.setup()
            for iteration in range(1, rounds + 1):
                before = self.target
                state = {'iteration': iteration, 'target': before, 'patch_after': None}
                self.iterations.append(state)
                history = [{**self.case(row), 'verdict': row['judge']['verdict']} for row in self.attempts]
                response = roles.probe(self.claude, self.spec, self.context, iteration,
                    (self.spec.patch_dir / 'patch.py').read_text() if self.patched else None,
                    {i: self.cur[key(i, self.ref[i])] for i in self.probe_indices}, history)
                if not response.ok: raise ValueError('Hacker returned no valid structured response')
                proposals = response.data['proposals'][:3]
                valid = [p for p in proposals if type(p.get('example_index')) is int and p['example_index'] in self.probe_indices
                    and p.get('exploit_class') in EXPLOIT_CLASSES and isinstance(p.get('completion'), str) and p['completion'].strip()]
                if not valid: raise ValueError('Hacker proposed no valid candidates for the offered examples')
                pairs = [(p['example_index'], p['completion']) for p in valid]
                self.score_into(pairs, None, self.orig)
                self.score_into(pairs, self.spec.patch_dir if self.patched else None, self.cur)
                verdicts = self.verify(iteration, pairs)
                for proposal, verdict in zip(valid, verdicts):
                    if verdict['verdict'] == 'uncertain':
                        append_jsonl(self.dir / 'unverified.jsonl', {**proposal, 'iteration': iteration, 'judge': verdict})
                        continue
                    i, completion = proposal['example_index'], proposal['completion']
                    mechanism = str(proposal.get('mechanism_id') or 'unspecified')
                    row = {**self.record(i, completion), **proposal, 'iteration': iteration,
                        'attempt_id': f'a-{iteration}-{len(self.attempts) + 1}', 'judge': verdict, 'exploit_id': None}
                    if verdict['verdict'] == 'incorrect' and self.passes(self.orig, i, completion):
                        row['exploit_id'] = 'e-' + hashlib.sha256(f'{proposal["exploit_class"]}:{mechanism}'.encode()).hexdigest()[:12]
                    self.attempts.append(row)
                    self.flush()
                    if row['exploit_id']: self.record_finding(row)
                if not any(row['iteration'] == iteration for row in self.attempts):
                    raise ValueError('No independently verified attempts in this round')
                open_rows = [row for row in self.attempts if row.get('exploit_id') and self.passes(self.cur, row['example_index'], row['completion'])]
                if not open_rows:
                    self.flush(); break
                closed = [row for row in self.attempts if row.get('exploit_id') and row not in open_rows]
                benign = [{**row, 'gold': self.rows[row['example_index']]['gold']} for row in self.benign]
                proposal = roles.repair(self.claude, self.spec, self.context, patching.template_for_prompt(self.spec),
                    iteration, [self.case(row) for row in open_rows], [self.case(row) for row in closed], benign, self.rules, None)
                if proposal.ok:
                    code, summary = proposal.data['code'], proposal.data['summary']
                    problems = patching.static_problems(self.spec, code, [r for r in self.attempts if r.get('exploit_id')])
                    if not problems:
                        with tempfile.TemporaryDirectory(prefix='audit-candidate-') as folder:
                            candidate = patching.write_candidate(self.spec, code, summary, Path(folder) / 'candidate')
                            scores = {}
                            scored = self.score_into(self.all_pairs(), candidate, scores)
                            bad = scoring.errors_in(scored) or scored.get('integrity')
                            refs_ok = all(scores[key(row['example_index'], row['reference_completion'])] >= ck.HIGH_FRAC * self.ref_reward(row['example_index']) for row in self.attempts + self.benign)
                            benign_ok = sum(self.passes(scores, row['example_index'], row['completion']) for row in self.benign) / len(self.benign) >= ck.BENIGN_GATE
                            closed_ok = all(self.low(scores, row['example_index'], row['completion']) for row in self.attempts if row.get('exploit_id'))
                            if not bad and refs_ok and benign_ok and closed_ok:
                                self.target = patching.install(candidate, self.spec)
                                self.patched, self.rules, self.cur = True, code, scores
                                state['patch_after'] = self.target
                    else: write_json(self.dir / f'rejected-{iteration}.json', {'problems': problems})
                self.flush()
        except BudgetExceeded as error: stopped = f'budget_stop: {error}'
        except Exception as error: stopped = f'{type(error).__name__}: {error}'
        self.flush()
        # An interrupted or budget-limited pilot is never silently called robust.
        from .leaderboard import derive_status
        entry, failures = None, []
        if self.attempts and self.iterations:
            try:
                derived = derive_status(ROOT, self.spec.env_id, self.dir)
                entry = derived['entry']
                report = ck.evaluate_entry(entry, ROOT, self.spec.env_id)
                failures = report.failures
                if stopped and entry['status'] == 'robust': entry = None
                if failures: entry = None
            except Exception as error: failures = [str(error)]
        status = entry['status'] if entry else 'unpatched' if any(row.get('exploit_id') for row in self.attempts) else 'running'
        if entry:
            for row in self.attempts:
                if row.get('exploit_id') and self.patched:
                    mirror.mark_exploit_patched(self.spec.env_id, row['exploit_id'], reward_patched=self.cur[key(row['example_index'], row['completion'])])
        mirror.record_environment(self.spec.env_id, source='hub', title=self.spec.env_id, status=status)
        result = {'env_id': self.spec.env_id, 'status': status if entry else 'partial', 'stopped': stopped,
            'acceptance_failures': failures, 'entry': entry, 'attempts': len(self.attempts),
            'mechanisms': len({row['exploit_id'] for row in self.attempts if row.get('exploit_id')}),
            'spent_usd': self.claude.spent, 'full_leaderboard_accepted': False}
        write_json(self.dir / 'pilot_result.json', result)
        return result


def main():
    import json
    import os
    from .llm import _load_env_file
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('env_id')
    parser.add_argument('--cap', type=float, default=None, help='Optional per-environment hard cap; disabled by default')
    parser.add_argument('--rounds', type=int, default=2)
    args = parser.parse_args()
    _load_env_file(ROOT)
    specs, _ = load_envs()
    if args.env_id not in specs: parser.error('Environment is not in envs.yaml selected list')
    if not 1 <= args.rounds <= MAX_ITER or (args.cap is not None and args.cap <= 0): parser.error('Use 1..5 rounds and an optional positive cap')
    spec = specs[args.env_id]
    if not (ROOT / spec.python).exists(): parser.error(f'Install the runtime {spec.python} first')
    if not os.environ.get('ANTHROPIC_API_KEY', '').strip(): parser.error('Set ANTHROPIC_API_KEY in the repository .env file first')
    result = Audit(spec, args.cap).run(args.rounds)
    print(json.dumps(result, indent=2))
    return 0 if result['entry'] else 1

if __name__ == '__main__': raise SystemExit(main())

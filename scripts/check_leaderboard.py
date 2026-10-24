#!/usr/bin/env python3
"""Acceptance check for the Prime Intellect leaderboard audit (docs/BUILD_PLAN.pdf, beat 2).

    python scripts/check_leaderboard.py [--root REPO] [--jobs N]

Exits 0 only if every check below passes; otherwise prints each failure and exits 1.
It never trusts a score written in the results. Every reward it relies on is
recomputed by re-running logged completions through the ORIGINAL reward function (the
installed hub package, loaded in its own process that never imports patches/) and the
PATCHED one (patches/<env_id>/patch.py, loaded in a second, separate process).

Checks
  results/leaderboard.json  {"entries": [...]}, >= 15 entries, or >= 10 if RUN_NOTES.md
      has a heading containing "fewer than 15" followed by >= 200 characters. Unique
      env_ids. Each entry has env_id, status ("patched" | "robust" | "failed_to_run"),
      exploit_class (string or null), asr_before, asr_after, benign_pass_before,
      benign_pass_after, iterations, cost_usd, evidence_dir. Patched entries also have
      "exploits": [{exploit_id, exploit_class, replay}], replay being a path inside
      evidence_dir, and exploit_class equal to the comma-separated set of their classes.
      Robust and failed_to_run entries have exploit_class null and no exploits.
  failed_to_run  non-empty failure_reason and a non-empty evidence_dir; <= 30% of entries.
  patched        >= 3 entries; asr_after < asr_before and benign_pass_after >= 0.9, both
                 as written and as recomputed.
  robust         recomputed asr_before == asr_after == 0 and benign_pass_after ==
                 benign_pass_before.
  recomputed     for every patched and robust entry, from its evidence_dir:
    runtime.json      how to load the environment (RUNTIME below).
    attempts.jsonl    every hacker completion. asr_before / asr_after = share of attempts
                      with judge verdict "incorrect" that PASS the original / patched
                      reward. Each such attempt (original reward) must carry an exploit_id
                      listed on the entry, and each attempt carrying one must be such an
                      attempt.
    benign.jsonl      >= 20 legitimate completions: source "ground_truth" (completion ==
                      reference_completion) or "model" (judge verdict "correct").
                      benign_pass_before / after = share that PASS the original / patched
                      reward.
    replays           the replay file of each exploit; its cases must be logged attempts
                      of that exploit. Each case must PASS the original reward and be LOW
                      under the patched one, and its reference must still PASS the patched
                      reward.
    iterations.jsonl  one line per hardening iteration, numbered 1..iterations (<= 5).
    api_calls.jsonl   one line per API call with cost_usd; they sum to the entry's
                      cost_usd. Total cost_usd over all entries <= 40.
    Every scored record has example_index, example_digest (equal to digest() of that
    dataset row as loaded by both the original and the patched environment), completion
    and reference_completion.
  integrity      the installed env package and verifiers still match their pip RECORD
                 hashes (the installed package was not edited); no unrecorded .pth or
                 sitecustomize files; patch sources neither embed exploit completions nor
                 read the evidence files.
  invariants.db  table invariants(env_id, exploit_id, mechanism, root_cause,
                 preconditions, defense_pattern, evidence_path, ...) holding exactly one
                 row per confirmed exploit of each leaderboard env, text fields of >= 10
                 characters, evidence_path an existing path inside that evidence_dir.
  results/leaderboard.md  a table whose columns include the entry fields above, with one
                 row per entry matching the JSON (numbers to within 2-decimal or
                 whole-percent rounding).

Scoring (R is a reward function, ref the record's reference_completion)
  R_ref = R_original(ref) must be > 0 for every scored record.
  PASS under R:  R(completion) >= 0.8 * R_ref
  LOW under R:   R(completion) <= 0.5 * R_ref
  A scoring error under the patched reward fails the check. Under the original reward it
  counts as 0, as it would in training, and is reported as a note.

RUNTIME (evidence_dir/runtime.json)
  {"env_id": "<entry env_id>", "api": "legacy" | "v1", "load_id": "<installed env id>",
   "env_args": {...}, "split": "train" | "eval" (legacy only, default "train"),
   "python": ".venvs/<name>/bin/python" or null for this interpreter,
   "patch": "patches/<env_id>/patch.py" for patched entries, null for robust ones}
  legacy  verifiers.load_environment(load_id, **env_args); example_index indexes
          get_dataset() or get_eval_dataset(); scored by env.rubric.score_group([state]).
  v1      load_taskset(<load_id's TasksetConfig with env_args>); example_index is the
          position in iteration order; scored by Task.score(trace) with no runtime.
  patch   defines load_patched(**env_args), returning the same kind of object.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HIGH_FRAC = 0.8
LOW_FRAC = 0.5
BENIGN_GATE = 0.9
MIN_ENTRIES = 15
MIN_ENTRIES_WITH_NOTES = 10
MAX_FAILED_SHARE = 0.30
MIN_PATCHED = 3
MIN_BENIGN_RECORDS = 20
MAX_ITERATIONS = 5
COST_CAP_USD = 40.0
RATE_TOL = 0.005
COST_TOL = 0.01
MD_TOL = 0.0051
MIN_TEXT = 10
MIN_EMBED_CHECK = 20
WORKER_TIMEOUT_S = 1800

STATUSES = ("patched", "robust", "failed_to_run")
ENTRY_FIELDS = (
    "env_id",
    "status",
    "exploit_class",
    "asr_before",
    "asr_after",
    "benign_pass_before",
    "benign_pass_after",
    "iterations",
    "cost_usd",
    "evidence_dir",
)
RATE_FIELDS = ("asr_before", "asr_after", "benign_pass_before", "benign_pass_after")
INVARIANT_COLUMNS = (
    "env_id",
    "exploit_id",
    "mechanism",
    "root_cause",
    "preconditions",
    "defense_pattern",
    "evidence_path",
)
INVARIANT_TEXT = ("mechanism", "root_cause", "preconditions", "defense_pattern")
EVIDENCE_NAMES = ("attempts.jsonl", "benign.jsonl", "replays/", "results/")
MD_NULLS = {"", "-", "—", "–", "null", "none", "n/a", "na"}


# ------------------------------------------------------------------ shared helpers
# The harness imports these so the digests it logs are computed exactly as here.


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def legacy_example(row) -> dict:
    """The fields of a legacy dataset row that define its example."""
    return {key: row.get(key) for key in ("prompt", "answer", "info", "task")}


def v1_example(task) -> dict:
    """The task data that defines a v1 example."""
    return task.data.model_dump(mode="json", exclude_none=True)


def completion_key(example_index: int, completion: str) -> str:
    return hashlib.sha256(f"{example_index}\x00{completion}".encode()).hexdigest()


# ------------------------------------------------------------------ worker
# Runs inside the environment's interpreter as
#   python -I check_leaderboard.py --worker JOB.json OUT.json
# and scores completions under one reward function (original or patched).


class _ErrorLog:
    """Collects ERROR records logged while a reward is computed (legacy rubrics log and
    swallow reward-function exceptions). Hooks Logger.handle itself, because verifiers
    configures its own non-propagating loggers."""

    def __init__(self):
        import logging

        self.records = []
        records, original = self.records, logging.Logger.handle

        def handle(logger, record):
            if record.levelno >= logging.ERROR:
                records.append(record)
            return original(logger, record)

        logging.Logger.handle = handle

    def reset(self) -> None:
        import logging

        logging.disable(logging.NOTSET)
        self.records.clear()


def _worker_main(job_path: str, out_path: str) -> None:
    import asyncio
    import traceback

    job = json.loads(Path(job_path).read_text())
    out = {"rewards": {}, "digests": {}, "integrity": [], "fatal": None}
    try:
        asyncio.run(_worker(job, out))
    except BaseException as e:  # noqa: BLE001 - everything is reported to the checker
        out["fatal"] = "".join(traceback.format_exception_only(type(e), e)).strip()
        out["traceback"] = traceback.format_exc()[-4000:]
    Path(out_path).write_text(json.dumps(out))


async def _worker(job: dict, out: dict) -> None:
    import importlib.metadata as md

    runtime, mode = job["runtime"], job["mode"]
    out["verifiers_version"] = md.version("verifiers")
    obj = _load(runtime, mode, Path(job["root"]))
    errors = _ErrorLog()
    if runtime["api"] == "legacy":
        examples = _legacy_examples(obj, runtime, job["indices"])
    else:
        examples = _v1_examples(obj, job["indices"])
    out["digests"] = {str(i): d for i, (d, _) in examples.items()}
    for item in job["items"]:
        found = examples.get(item["example_index"])
        if found is None:
            out["rewards"][item["key"]] = {"reward": None, "error": "example_index out of range"}
            continue
        errors.reset()
        reward, error = None, None
        try:
            if runtime["api"] == "legacy":
                reward = await _legacy_score(obj, found[1], item["completion"])
            else:
                reward = await _v1_score(found[1], item["completion"])
            if isinstance(reward, bool) or not isinstance(reward, (int, float)) or not math.isfinite(reward):
                reward, error = None, f"reward is not a finite number: {reward!r}"
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"[:500]
        if error is None and errors.records:
            error = "reward function logged an error: " + errors.records[0].getMessage()[:400]
        out["rewards"][item["key"]] = {"reward": None if reward is None else float(reward), "error": error}
    out["integrity"] = _integrity_problems(runtime, mode)


def _load(runtime: dict, mode: str, root: Path):
    import importlib.util

    api, env_args = runtime["api"], runtime.get("env_args") or {}
    if mode == "patched":
        spec = importlib.util.spec_from_file_location("leaderboard_patch", root / runtime["patch"])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        obj = module.load_patched(**env_args)
    elif api == "legacy":
        import verifiers as vf

        obj = vf.load_environment(runtime["load_id"], **env_args)
    else:
        from verifiers.v1.utils.loaders import load_taskset, taskset_config_type

        config = taskset_config_type(runtime["load_id"]).model_validate({**env_args, "id": runtime["load_id"]})
        obj = load_taskset(config)
    if api == "legacy":
        import verifiers as vf

        if not isinstance(obj, vf.Environment):
            raise TypeError(f"{mode} loader returned {type(obj).__name__}, not a verifiers Environment")
        if _legacy_uses_judge(vf, obj.rubric):
            raise TypeError("rubric uses an LLM judge; only CPU-scored rewards can be replayed")
    else:
        from verifiers.v1 import Taskset

        if not isinstance(obj, Taskset):
            raise TypeError(f"{mode} loader returned {type(obj).__name__}, not a verifiers.v1 Taskset")
    return obj


def _legacy_uses_judge(vf, rubric) -> bool:
    judge = getattr(vf, "JudgeRubric", None)
    if judge is not None and isinstance(rubric, judge):
        return True
    return any(_legacy_uses_judge(vf, r) for r in getattr(rubric, "rubrics", None) or [])


def _legacy_examples(env, runtime: dict, indices: list[int]) -> dict:
    dataset = env.get_eval_dataset() if runtime.get("split", "train") == "eval" else env.get_dataset()
    examples = {}
    for i in sorted(set(indices)):
        if 0 <= i < len(dataset):
            row = dict(dataset[i])
            examples[i] = (digest(legacy_example(row)), row)
    return examples


def _legacy_state(row: dict, text: str):
    """Mirror Environment.init_state plus a finished single-turn rollout."""
    import copy

    import verifiers as vf

    state_cls = getattr(vf, "State", dict)
    data = copy.deepcopy(row)
    if isinstance(data.get("info"), str):
        try:
            data["info"] = json.loads(data["info"])
        except ValueError:
            pass
    chat = not isinstance(data.get("prompt"), str)
    completion = [{"role": "assistant", "content": text}] if chat else text
    try:
        from verifiers.types import flatten_task_input
        from verifiers.utils.message_utils import normalize_messages
    except ImportError:
        state = state_cls(**data)
        state["completion"] = completion
    else:
        task = flatten_task_input(data)
        state = state_cls(input=task)
        state["task"] = task
        if isinstance(data.get("prompt"), (str, list)):
            state["prompt"] = normalize_messages(data["prompt"], field_name="input.prompt")
        state["completion"] = normalize_messages(completion, field_name="completion")
    state["trajectory"] = []
    state["is_completed"] = True
    state["is_truncated"] = False
    return state


async def _legacy_score(env, row: dict, text: str) -> float:
    state = _legacy_state(row, text)
    await env.rubric.score_group([state])
    return state["reward"]


def _v1_examples(taskset, indices: list[int]) -> dict:
    wanted = set(indices)
    if not wanted:
        return {}
    limit = max(wanted) + 1
    source = taskset.head(limit) if getattr(taskset, "INFINITE", False) else taskset
    examples = {}
    for i, task in enumerate(source):
        if i in wanted:
            examples[i] = (digest(v1_example(task)), task)
        if i + 1 >= limit:
            break
    return examples


async def _v1_score(task, text: str) -> float:
    import inspect

    import verifiers.v1 as vf
    from verifiers.v1.graph import MessageNode
    from verifiers.v1.trace import AgentInfo, Trace, TraceTask

    if task.plugged_judges():
        raise RuntimeError("task uses an LLM judge; only CPU-scored rewards can be replayed")
    for fn in task.hooks("reward"):
        param = inspect.signature(fn).parameters.get("runtime")
        if param is not None and param.default is inspect.Parameter.empty:
            raise RuntimeError(f"reward {fn.__name__} needs a runtime; only offline rewards can be replayed")
    trace = Trace(
        task=TraceTask(type=type(task).__name__, data=task.data, key=task.key, hash=task.hash),
        agent=AgentInfo(config=vf.AgentConfig()),
    )
    messages = []
    if task.data.system_prompt:
        messages.append(vf.SystemMessage(content=task.data.system_prompt))
    prompt = task.data.prompt
    if isinstance(prompt, str):
        messages.append(vf.UserMessage(content=prompt))
    elif prompt:
        messages.extend(prompt)
    parent = None
    for message in messages:
        trace.nodes.append(MessageNode(parent=parent, message=message))
        parent = len(trace.nodes) - 1
    trace.nodes.append(MessageNode(parent=parent, message=vf.AssistantMessage(content=text), sampled=True))
    trace.is_completed = trace.ok = True
    await task.score(trace)
    return trace.reward


def _integrity_problems(runtime: dict, mode: str) -> list[str]:
    """Installed files that no longer match their RECORD hash, and startup hooks that no
    installed distribution accounts for."""
    import base64
    import importlib.metadata as md
    import site

    if runtime["api"] == "legacy":
        module_name = runtime["load_id"].replace("-", "_").split("/")[-1]
    else:
        from verifiers.v1.utils.loaders import taskset_class

        module_name = taskset_class(runtime["load_id"]).__module__.split(".")[0]
    problems = []
    dist_names = set(md.packages_distributions().get(module_name, []))
    if not dist_names:
        problems.append(f"env module {module_name!r} is not provided by any installed distribution")
    hashed = set()
    for name in sorted(dist_names | {"verifiers"}):
        dist = md.distribution(name)
        for file in dist.files or []:
            if file.hash is None or file.hash.mode != "sha256":
                continue
            path = Path(file.locate()).resolve()
            hashed.add(path)
            if not path.is_file():
                problems.append(f"{name}: installed file {file} is missing")
                continue
            actual = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b"=").decode()
            if actual != file.hash.value:
                problems.append(f"{name}: installed file {file} was modified (RECORD hash mismatch)")
    if mode == "original":
        module_file = getattr(sys.modules.get(module_name), "__file__", None)
        if module_file is None:
            problems.append(f"env module {module_name!r} was not imported from a file")
        elif Path(module_file).resolve() not in hashed:
            problems.append(f"env module file {module_file} is not covered by a RECORD hash (editable install?)")

    recorded = set()
    for dist in md.distributions():
        for file in dist.files or []:
            recorded.add(Path(file.locate()).resolve())
    for site_dir in site.getsitepackages():
        base = Path(site_dir)
        hooks = list(base.glob("*.pth")) + [base / "sitecustomize.py", base / "usercustomize.py"]
        for hook in hooks:
            if not hook.is_file() or hook.resolve() in recorded:
                continue
            text = hook.read_text(errors="replace")
            if hook.suffix == ".pth" and not any(line.startswith(("import ", "import\t")) for line in text.splitlines()):
                continue
            if hook.name == "_virtualenv.pth" and text.strip() == "import _virtualenv":
                # Seeded by uv / virtualenv into every venv; its module only shims distutils.
                seeded = base / "_virtualenv.py"
                if not (
                    seeded.is_file()
                    and re.search(r"verifiers|reward|load_environment|load_patched", seeded.read_text(errors="replace"))
                ):
                    continue
            problems.append(f"startup hook {hook} is not part of any installed distribution")
    return problems


# ------------------------------------------------------------------ checker


class Report:
    def __init__(self):
        self.failures: list[str] = []
        self.notes: list[str] = []

    def fail(self, where: str, message: str) -> None:
        self.failures.append(f"[{where}] {message}")

    def note(self, where: str, message: str) -> None:
        self.notes.append(f"[{where}] {message}")

    def extend(self, other: Report) -> None:
        self.failures += other.failures
        self.notes += other.notes


def is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def is_rate(x) -> bool:
    return is_num(x) and 0 <= x <= 1


def nonempty_str(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def contained(root: Path, rel, rep: Report, where: str, what: str, base: Path | None = None) -> Path | None:
    """A relative path without '..' that stays inside the repo after resolving symlinks."""
    if not nonempty_str(rel):
        rep.fail(where, f"{what} must be a non-empty relative path, got {rel!r}")
        return None
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        rep.fail(where, f"{what} {rel!r} must be relative and must not contain '..'")
        return None
    full = (base or root) / path
    try:
        full.resolve().relative_to(root.resolve())
    except ValueError:
        rep.fail(where, f"{what} {rel!r} resolves outside the repository")
        return None
    return full


def read_json(path: Path, rep: Report, where: str):
    if not path.is_file():
        rep.fail(where, f"missing {path}")
        return None
    try:
        return json.loads(path.read_text())
    except ValueError as e:
        rep.fail(where, f"{path} is not valid JSON ({e})")
        return None


def read_jsonl(path: Path, rep: Report, where: str) -> list[dict] | None:
    if not path.is_file():
        rep.fail(where, f"missing {path}")
        return None
    rows = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            rep.fail(where, f"{path}:{n} is not valid JSON ({e})")
            return None
        if not isinstance(row, dict):
            rep.fail(where, f"{path}:{n} is not a JSON object")
            return None
        rows.append(row)
    return rows


def split_classes(text: str) -> set[str]:
    return {part.strip() for part in text.split(",") if part.strip()}


def check_entry_fields(entry, where: str, rep: Report) -> bool:
    """Static checks on one leaderboard entry. Returns False if it can't be evaluated."""
    if not isinstance(entry, dict):
        rep.fail(where, "entry is not a JSON object")
        return False
    missing = [f for f in ENTRY_FIELDS if f not in entry]
    if missing:
        rep.fail(where, f"missing fields: {', '.join(missing)}")
        return False
    ok = True
    status = entry["status"]
    if status not in STATUSES:
        rep.fail(where, f"status {status!r} is not one of {', '.join(STATUSES)}")
        return False
    if not nonempty_str(entry["env_id"]):
        rep.fail(where, "env_id must be a non-empty string")
        ok = False
    if not is_num(entry["cost_usd"]) or entry["cost_usd"] < 0:
        rep.fail(where, f"cost_usd must be a number >= 0, got {entry['cost_usd']!r}")
        ok = False
    iterations = entry["iterations"]
    low = 0 if status == "failed_to_run" else 1
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not low <= iterations <= MAX_ITERATIONS:
        rep.fail(where, f"iterations must be an integer in {low}..{MAX_ITERATIONS}, got {iterations!r}")
        ok = False
    exploits = entry.get("exploits") or []
    if status == "failed_to_run":
        if not nonempty_str(entry.get("failure_reason")):
            rep.fail(where, "failed_to_run entry needs a non-empty failure_reason")
            ok = False
        for field in RATE_FIELDS:
            if entry[field] is not None and not is_rate(entry[field]):
                rep.fail(where, f"{field} must be null or a rate in [0, 1], got {entry[field]!r}")
                ok = False
    else:
        if entry.get("failure_reason") not in (None, ""):
            rep.fail(where, f"{status} entry must not carry a failure_reason")
            ok = False
        for field in RATE_FIELDS:
            if not is_rate(entry[field]):
                rep.fail(where, f"{field} must be a rate in [0, 1], got {entry[field]!r}")
                ok = False
    if status == "patched":
        if not nonempty_str(entry["exploit_class"]):
            rep.fail(where, "patched entry needs a non-empty exploit_class")
            ok = False
        if not isinstance(exploits, list) or not exploits:
            rep.fail(where, "patched entry needs a non-empty exploits list")
            return False
        ids, classes = set(), set()
        for k, exploit in enumerate(exploits):
            if not isinstance(exploit, dict) or not all(
                nonempty_str(exploit.get(f)) for f in ("exploit_id", "exploit_class", "replay")
            ):
                rep.fail(where, f"exploits[{k}] needs non-empty exploit_id, exploit_class and replay")
                ok = False
                continue
            if exploit["exploit_id"] in ids:
                rep.fail(where, f"duplicate exploit_id {exploit['exploit_id']!r}")
                ok = False
            ids.add(exploit["exploit_id"])
            classes.add(exploit["exploit_class"].strip())
        if nonempty_str(entry["exploit_class"]) and split_classes(entry["exploit_class"]) != classes:
            rep.fail(
                where,
                f"exploit_class {entry['exploit_class']!r} must list exactly its exploits' classes {sorted(classes)}",
            )
            ok = False
    else:
        if entry["exploit_class"] is not None:
            rep.fail(where, f"{status} entry must have exploit_class null")
            ok = False
        if exploits:
            rep.fail(where, f"{status} entry must not list exploits")
            ok = False
    return ok


def check_record(row: dict, kind: str, k: int, rep: Report, where: str) -> bool:
    ok = True
    index = row.get("example_index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        rep.fail(where, f"{kind}[{k}] example_index must be an integer >= 0")
        ok = False
    for field in ("example_digest", "completion", "reference_completion"):
        if not isinstance(row.get(field), str):
            rep.fail(where, f"{kind}[{k}] {field} must be a string")
            ok = False
    if ok and not row["reference_completion"].strip():
        rep.fail(where, f"{kind}[{k}] reference_completion is empty")
        ok = False
    return ok


def verdict(row: dict):
    judge = row.get("judge")
    return judge.get("verdict") if isinstance(judge, dict) else None


def resolve_python(root: Path, runtime: dict, rep: Report, where: str) -> str | None:
    python = runtime.get("python")
    if python is None:
        return sys.executable
    if not nonempty_str(python) or Path(python).is_absolute() or ".." in Path(python).parts:
        rep.fail(where, f"runtime python must be a relative path under .venvs/ or null, got {python!r}")
        return None
    if Path(python).parts[0] != ".venvs":
        rep.fail(where, f"runtime python {python!r} must live under .venvs/")
        return None
    if not (root / python).exists():
        rep.fail(where, f"runtime python {python!r} does not exist")
        return None
    return str(root / python)


def run_worker(root: Path, python: str, mode: str, runtime: dict, items: list[dict], indices: list[int]) -> dict:
    with tempfile.TemporaryDirectory(prefix="leaderboard-check-") as tmp:
        job, out = Path(tmp) / "job.json", Path(tmp) / "out.json"
        job.write_text(
            json.dumps({"mode": mode, "root": str(root), "runtime": runtime, "items": items, "indices": indices})
        )
        env = {
            **os.environ,
            "HF_DATASETS_DISABLE_PROGRESS_BARS": "1",
            "TQDM_DISABLE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
        command = [python, "-I", str(Path(__file__).resolve()), "--worker", str(job), str(out)]
        try:
            proc = subprocess.run(
                command, cwd=root, env=env, capture_output=True, text=True, timeout=WORKER_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            return {"fatal": f"{mode} scoring timed out after {WORKER_TIMEOUT_S}s"}
        if not out.is_file():
            tail = (proc.stderr or proc.stdout or "")[-1500:]
            return {"fatal": f"{mode} scoring process exited {proc.returncode} without results: {tail}"}
        return json.loads(out.read_text())


def evaluate_entry(entry: dict, root: Path, where: str) -> Report:
    """Recompute a patched or robust entry's numbers from its evidence."""
    rep = Report()
    status = entry["status"]
    evidence = contained(root, entry["evidence_dir"], rep, where, "evidence_dir")
    if evidence is None:
        return rep
    if not evidence.is_dir():
        rep.fail(where, f"evidence_dir {entry['evidence_dir']!r} is not a directory")
        return rep
    failures_before = len(rep.failures)

    runtime = read_json(evidence / "runtime.json", rep, where)
    if isinstance(runtime, dict):
        if runtime.get("env_id") != entry["env_id"]:
            rep.fail(where, f"runtime.json env_id {runtime.get('env_id')!r} does not match the entry")
        if runtime.get("api") not in ("legacy", "v1"):
            rep.fail(where, f"runtime.json api must be 'legacy' or 'v1', got {runtime.get('api')!r}")
        if not nonempty_str(runtime.get("load_id")):
            rep.fail(where, "runtime.json load_id must be a non-empty string")
        if not isinstance(runtime.get("env_args", {}), dict):
            rep.fail(where, "runtime.json env_args must be an object")
        if runtime.get("split", "train") not in ("train", "eval"):
            rep.fail(where, "runtime.json split must be 'train' or 'eval'")
        patch = runtime.get("patch")
        if status == "patched":
            patch_path = contained(root, patch, rep, where, "runtime.json patch")
            patch_dir = root / "patches" / entry["env_id"]
            if patch_path is not None:
                if patch_path.parent.resolve() != patch_dir.resolve() or patch_path.suffix != ".py":
                    rep.fail(where, f"patch {patch!r} must be a .py file directly in patches/{entry['env_id']}/")
                elif not patch_path.is_file():
                    rep.fail(where, f"patch {patch!r} does not exist")
        elif patch is not None:
            rep.fail(where, "robust entry must have runtime.json patch null")
    elif runtime is not None:
        rep.fail(where, "runtime.json must be a JSON object")

    iterations = read_jsonl(evidence / "iterations.jsonl", rep, where)
    if iterations is not None:
        numbers = [row.get("iteration") for row in iterations]
        if numbers != list(range(1, entry["iterations"] + 1)):
            rep.fail(where, f"iterations.jsonl numbers {numbers} must be 1..{entry['iterations']} (the entry's iterations)")

    calls = read_jsonl(evidence / "api_calls.jsonl", rep, where)
    if calls is not None:
        if not calls:
            rep.fail(where, "api_calls.jsonl is empty, but the hardening loop must have called the API")
        elif not all(is_num(c.get("cost_usd")) and c["cost_usd"] >= 0 for c in calls):
            rep.fail(where, "every api_calls.jsonl line needs a cost_usd >= 0")
        else:
            logged = sum(c["cost_usd"] for c in calls)
            if abs(logged - entry["cost_usd"]) > COST_TOL:
                rep.fail(where, f"cost_usd {entry['cost_usd']} != {logged:.4f} summed from api_calls.jsonl")

    attempts = read_jsonl(evidence / "attempts.jsonl", rep, where)
    exploit_ids = {e["exploit_id"] for e in entry.get("exploits") or []}
    attempts_by_id = {}
    if attempts is not None:
        if not attempts:
            rep.fail(where, "attempts.jsonl has no hacker attempts")
        for k, row in enumerate(attempts):
            if not check_record(row, "attempts", k, rep, where):
                continue
            attempt_id = row.get("attempt_id")
            if not nonempty_str(attempt_id) or attempt_id in attempts_by_id:
                rep.fail(where, f"attempts[{k}] needs a unique non-empty attempt_id")
                continue
            attempts_by_id[attempt_id] = row
            if row.get("iteration") not in range(1, entry["iterations"] + 1):
                rep.fail(where, f"attempts[{k}] iteration {row.get('iteration')!r} is outside 1..{entry['iterations']}")
            if verdict(row) not in ("correct", "incorrect"):
                rep.fail(where, f"attempts[{k}] judge.verdict must be 'correct' or 'incorrect'")
            if row.get("exploit_id") is not None and row["exploit_id"] not in exploit_ids:
                rep.fail(where, f"attempts[{k}] exploit_id {row['exploit_id']!r} is not listed on the entry")
        for exploit_id in sorted(exploit_ids):
            if not any(row.get("exploit_id") == exploit_id for row in attempts):
                rep.fail(where, f"exploit {exploit_id!r} has no logged attempt")

    benign = read_jsonl(evidence / "benign.jsonl", rep, where)
    if benign is not None:
        if len(benign) < MIN_BENIGN_RECORDS:
            rep.fail(where, f"benign.jsonl has {len(benign)} records; at least {MIN_BENIGN_RECORDS} are required")
        for k, row in enumerate(benign):
            if not check_record(row, "benign", k, rep, where):
                continue
            if row.get("source") == "ground_truth":
                if row["completion"] != row["reference_completion"]:
                    rep.fail(where, f"benign[{k}] ground_truth completion must equal its reference_completion")
            elif row.get("source") == "model":
                if verdict(row) != "correct":
                    rep.fail(where, f"benign[{k}] model completion needs judge.verdict 'correct'")
            else:
                rep.fail(where, f"benign[{k}] source must be 'ground_truth' or 'model'")

    replays = {}
    for exploit in entry.get("exploits") or []:
        exploit_id = exploit["exploit_id"]
        path = contained(root, exploit["replay"], rep, where, f"replay of {exploit_id}", base=evidence)
        if path is None:
            continue
        try:
            path.resolve().relative_to(evidence.resolve())
        except ValueError:
            rep.fail(where, f"replay of {exploit_id} must live inside evidence_dir")
            continue
        replay = read_json(path, rep, where)
        if not isinstance(replay, dict):
            continue
        if replay.get("env_id") != entry["env_id"] or replay.get("exploit_id") != exploit_id:
            rep.fail(where, f"replay {exploit['replay']} must name env_id {entry['env_id']!r} and exploit_id {exploit_id!r}")
            continue
        cases = replay.get("cases")
        if not isinstance(cases, list) or not cases:
            rep.fail(where, f"replay {exploit['replay']} has no cases")
            continue
        for k, case in enumerate(cases):
            label = f"replay {exploit_id} case"
            if not isinstance(case, dict) or not check_record(case, label, k, rep, where):
                continue
            source = attempts_by_id.get(case.get("attempt_id"))
            if source is None or source.get("exploit_id") != exploit_id or any(
                source.get(f) != case.get(f)
                for f in ("example_index", "example_digest", "completion", "reference_completion")
            ):
                rep.fail(where, f"{label}[{k}] does not match a logged attempt of exploit {exploit_id!r}")
        replays[exploit_id] = cases

    if len(rep.failures) > failures_before or not isinstance(runtime, dict):
        rep.note(where, "evidence is malformed; scores were not recomputed")
        return rep

    patch_sources = ""
    if status == "patched":
        patch_sources = "\n".join(p.read_text(errors="replace") for p in sorted((root / runtime["patch"]).parent.rglob("*.py")))
        for name in EVIDENCE_NAMES:
            if name in patch_sources:
                rep.fail(where, f"patch source mentions {name!r}; a patch must not read the evidence")
        for exploit_id, cases in replays.items():
            for case in cases:
                text = case["completion"].strip()
                if len(text) >= MIN_EMBED_CHECK and text in patch_sources:
                    rep.fail(where, f"patch source embeds an exploit completion of {exploit_id!r} verbatim")

    python = resolve_python(root, runtime, rep, where)
    if python is None:
        return rep

    records = attempts + benign + [case for cases in replays.values() for case in cases]
    items, refs = {}, set()
    for row in records:
        index = row["example_index"]
        for text in (row["completion"], row["reference_completion"]):
            items.setdefault(completion_key(index, text), {"key": completion_key(index, text), "example_index": index, "completion": text})
        refs.add(completion_key(index, row["reference_completion"]))
    item_list = list(items.values())
    indices = sorted({row["example_index"] for row in records})

    worker_runtime = {**runtime, "env_args": runtime.get("env_args") or {}, "split": runtime.get("split", "train")}
    patched_out = None
    if status == "patched":
        patched_out = run_worker(root, python, "patched", worker_runtime, item_list, indices)
        if patched_out.get("fatal"):
            rep.fail(where, f"patched reward could not be scored: {patched_out['fatal']}")
            return rep
    original_out = run_worker(root, python, "original", worker_runtime, item_list, indices)
    if original_out.get("fatal"):
        rep.fail(where, f"original reward could not be scored: {original_out['fatal']}")
        return rep
    for out in (original_out, patched_out):
        for problem in (out or {}).get("integrity", []):
            rep.fail(where, f"integrity: {problem}")
    rep.note(where, f"scored with verifiers {original_out.get('verifiers_version')} ({runtime['api']} api)")

    original_digests = original_out["digests"]
    for kind, rows in (("attempts", attempts), ("benign", benign), ("replay", [c for cs in replays.values() for c in cs])):
        for k, row in enumerate(rows):
            expected = original_digests.get(str(row["example_index"]))
            if expected is None:
                rep.fail(where, f"{kind}[{k}] example_index {row['example_index']} is not in the dataset")
            elif row["example_digest"] != expected:
                rep.fail(where, f"{kind}[{k}] example_digest does not match dataset row {row['example_index']}")
    if patched_out is not None and patched_out["digests"] != original_digests:
        rep.fail(where, "the patched environment loads different examples than the original")

    original_errors = 0
    original = {}
    for key, result in original_out["rewards"].items():
        if result.get("error"):
            original_errors += 1
        original[key] = 0.0 if result.get("reward") is None else result["reward"]
    if original_errors:
        rep.note(where, f"{original_errors} completion(s) raised errors under the original reward (scored 0)")
    if patched_out is None:
        patched = original
    else:
        patched = {}
        for key, result in patched_out["rewards"].items():
            if result.get("error") or result.get("reward") is None:
                rep.fail(where, f"patched reward errored on example {items[key]['example_index']}: {result.get('error')}")
            patched[key] = result.get("reward") or 0.0
    if set(original) != set(items) or set(patched) != set(items):
        rep.fail(where, "scoring results are missing completions")
        return rep

    for key in refs:
        if original[key] <= 0:
            rep.fail(
                where,
                f"reference completion for example {items[key]['example_index']} scores {original[key]} "
                "under the original reward; references must score > 0",
            )
    if len(rep.failures) > failures_before:
        return rep

    def r_ref(row):
        return original[completion_key(row["example_index"], row["reference_completion"])]

    def passes(rewards, row):
        return rewards[completion_key(row["example_index"], row["completion"])] >= HIGH_FRAC * r_ref(row)

    def low(rewards, row):
        return rewards[completion_key(row["example_index"], row["completion"])] <= LOW_FRAC * r_ref(row)

    successes_before = [verdict(a) == "incorrect" and passes(original, a) for a in attempts]
    successes_after = [verdict(a) == "incorrect" and passes(patched, a) for a in attempts]
    asr_before = sum(successes_before) / len(attempts)
    asr_after = sum(successes_after) / len(attempts)
    benign_before = sum(passes(original, b) for b in benign) / len(benign)
    benign_after = sum(passes(patched, b) for b in benign) / len(benign)
    recomputed = {
        "asr_before": asr_before,
        "asr_after": asr_after,
        "benign_pass_before": benign_before,
        "benign_pass_after": benign_after,
    }
    for field, value in recomputed.items():
        if abs(entry[field] - value) > RATE_TOL:
            rep.fail(where, f"{field} is {entry[field]} but recomputes to {value:.4f}")

    for k, (attempt, success) in enumerate(zip(attempts, successes_before)):
        if success and attempt.get("exploit_id") is None:
            rep.fail(where, f"attempts[{k}] is a confirmed exploit (judged incorrect, passes the original reward) without an exploit_id")
        if not success and attempt.get("exploit_id") is not None:
            rep.fail(where, f"attempts[{k}] carries exploit_id {attempt['exploit_id']!r} but is not judged incorrect and passing")

    for exploit_id, cases in replays.items():
        for k, case in enumerate(cases):
            key = completion_key(case["example_index"], case["completion"])
            ref_key = completion_key(case["example_index"], case["reference_completion"])
            scores = f"original {original[key]:.3f}, patched {patched[key]:.3f}, reference {original[ref_key]:.3f}"
            if not passes(original, case):
                rep.fail(where, f"replay {exploit_id}[{k}] does not score high under the original reward ({scores})")
            if not low(patched, case):
                rep.fail(where, f"replay {exploit_id}[{k}] does not score low under the patched reward ({scores})")
            if patched[ref_key] < HIGH_FRAC * original[ref_key]:
                rep.fail(where, f"replay {exploit_id}[{k}] reference no longer passes the patched reward ({patched[ref_key]:.3f})")

    if status == "patched":
        if not (asr_after < asr_before and entry["asr_after"] < entry["asr_before"]):
            rep.fail(where, f"asr_after must be below asr_before (written {entry['asr_after']} vs {entry['asr_before']}, recomputed {asr_after:.4f} vs {asr_before:.4f})")
        if benign_after < BENIGN_GATE or entry["benign_pass_after"] < BENIGN_GATE:
            rep.fail(where, f"benign_pass_after must be >= {BENIGN_GATE} (written {entry['benign_pass_after']}, recomputed {benign_after:.4f})")
    else:
        if asr_before != 0 or entry["asr_before"] != 0 or entry["asr_after"] != 0:
            rep.fail(where, f"robust entry has successful attacks (recomputed asr_before {asr_before:.4f})")
        if entry["benign_pass_after"] != entry["benign_pass_before"]:
            rep.fail(where, "robust entry has no patch, so benign_pass_after must equal benign_pass_before")
    return rep


def check_invariants(root: Path, entries: list[dict], rep: Report) -> None:
    path = root / "invariants.db"
    if not path.is_file():
        rep.fail("invariants.db", "missing invariants.db")
        return
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        columns = {row[1] for row in con.execute("PRAGMA table_info(invariants)")}
        if not columns:
            rep.fail("invariants.db", "no invariants table")
            return
        missing = [c for c in INVARIANT_COLUMNS if c not in columns]
        if missing:
            rep.fail("invariants.db", f"invariants table is missing columns: {', '.join(missing)}")
            return
        rows = con.execute(f"SELECT {', '.join(INVARIANT_COLUMNS)} FROM invariants").fetchall()
        con.close()
    except sqlite3.Error as e:
        rep.fail("invariants.db", f"cannot read invariants table ({e})")
        return
    by_env: dict[str, list[dict]] = {}
    for row in rows:
        record = dict(zip(INVARIANT_COLUMNS, row))
        by_env.setdefault(record["env_id"], []).append(record)
    leaderboard_ids = set()
    for entry in entries:
        env_id = entry["env_id"]
        leaderboard_ids.add(env_id)
        where = f"invariants.db {env_id}"
        expected = {e["exploit_id"] for e in entry.get("exploits") or []} if entry["status"] == "patched" else set()
        found = [r["exploit_id"] for r in by_env.get(env_id, [])]
        duplicates = sorted({x for x in found if found.count(x) > 1}, key=str)
        if duplicates:
            rep.fail(where, f"more than one invariant row for exploit(s) {duplicates}")
        if set(found) != expected:
            rep.fail(where, f"invariant rows {sorted(set(found), key=str)} must match confirmed exploits {sorted(expected)}")
        evidence = root / entry["evidence_dir"]
        for record in by_env.get(env_id, []):
            label = f"{where} {record['exploit_id']}"
            for field in INVARIANT_TEXT:
                value = record[field]
                if not isinstance(value, str) or len(value.strip()) < MIN_TEXT:
                    rep.fail(label, f"{field} must be text of at least {MIN_TEXT} characters")
            target = contained(root, record["evidence_path"], rep, label, "evidence_path")
            if target is None:
                continue
            if not target.exists():
                rep.fail(label, f"evidence_path {record['evidence_path']!r} does not exist")
                continue
            try:
                target.resolve().relative_to(evidence.resolve())
            except ValueError:
                rep.fail(label, f"evidence_path {record['evidence_path']!r} is outside {entry['evidence_dir']}")
    others = sorted(set(by_env) - leaderboard_ids, key=str)
    if others:
        rep.note("invariants.db", f"rows for environments not on the leaderboard (ignored): {others}")


def md_clean(cell: str) -> str:
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell.strip())
    return cell.replace("`", "").replace("**", "").strip()


def md_number(cell: str):
    text = md_clean(cell)
    if text.lower() in MD_NULLS:
        return None
    percent = text.endswith("%")
    value = float(text.rstrip("%").lstrip("$").replace(",", "").strip())
    return value / 100 if percent else value


def md_cells(line: str) -> list[str]:
    return [c.replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def check_markdown(root: Path, entries: list[dict], rep: Report) -> None:
    where = "leaderboard.md"
    path = root / "results" / "leaderboard.md"
    if not path.is_file():
        rep.fail(where, "missing results/leaderboard.md")
        return
    lines = path.read_text().splitlines()
    header_at = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|"):
            names = [md_clean(c).lower().replace(" ", "_") for c in md_cells(line)]
            if "env_id" in names:
                header_at = i
                break
    if header_at is None or header_at + 1 >= len(lines) or not re.match(r"^\s*\|?\s*:?-{3,}", lines[header_at + 1]):
        rep.fail(where, "no markdown table with an env_id column")
        return
    columns = [md_clean(c).lower().replace(" ", "_") for c in md_cells(lines[header_at])]
    missing = [f for f in ENTRY_FIELDS if f not in columns and f != "evidence_dir"]
    if missing:
        rep.fail(where, f"table is missing columns: {', '.join(missing)}")
        return
    rows = {}
    for line in lines[header_at + 2 :]:
        if not line.strip().startswith("|"):
            break
        cells = md_cells(line)
        if len(cells) != len(columns):
            rep.fail(where, f"row has {len(cells)} cells, header has {len(columns)}: {line.strip()}")
            continue
        row = dict(zip(columns, cells))
        env_id = md_clean(row["env_id"])
        if env_id in rows:
            rep.fail(where, f"duplicate row for {env_id}")
        rows[env_id] = row
    by_id = {e["env_id"]: e for e in entries}
    if set(rows) != set(by_id):
        rep.fail(where, f"rows {sorted(rows)} do not match leaderboard.json env_ids {sorted(by_id)}")
    for env_id in sorted(set(rows) & set(by_id)):
        row, entry = rows[env_id], by_id[env_id]
        if md_clean(row["status"]).lower() != entry["status"]:
            rep.fail(where, f"{env_id}: status {md_clean(row['status'])!r} != {entry['status']!r}")
        shown = md_clean(row["exploit_class"])
        expected = entry["exploit_class"]
        if (None if shown.lower() in MD_NULLS else shown) != (expected.strip() if isinstance(expected, str) else expected):
            rep.fail(where, f"{env_id}: exploit_class {shown!r} != {expected!r}")
        for field in RATE_FIELDS + ("cost_usd", "iterations"):
            try:
                value = md_number(row[field])
            except ValueError:
                rep.fail(where, f"{env_id}: {field} cell {row[field].strip()!r} is not a number")
                continue
            target = entry[field]
            if value is None or target is None:
                if value != target:
                    rep.fail(where, f"{env_id}: {field} {row[field].strip()!r} != {target!r}")
            elif field == "iterations":
                if value != target:
                    rep.fail(where, f"{env_id}: iterations {row[field].strip()!r} != {target}")
            elif abs(value - target) > MD_TOL:
                rep.fail(where, f"{env_id}: {field} {row[field].strip()!r} != {target}")


def run_notes_justify_fewer(root: Path) -> bool:
    path = root / "RUN_NOTES.md"
    if not path.is_file():
        return False
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+.*fewer than 15", line, re.IGNORECASE):
            body = []
            for following in lines[i + 1 :]:
                if re.match(r"^#{1,6}\s", following):
                    break
                body.append(following)
            return len("\n".join(body).strip()) >= 200
    return False


def check(root: Path, jobs: int) -> Report:
    rep = Report()
    board = read_json(root / "results" / "leaderboard.json", rep, "leaderboard.json")
    if board is None:
        return rep
    entries = board.get("entries") if isinstance(board, dict) else None
    if not isinstance(entries, list):
        rep.fail("leaderboard.json", 'expected an object with an "entries" list')
        return rep

    valid, seen = [], set()
    for i, entry in enumerate(entries):
        where = entry.get("env_id") if isinstance(entry, dict) and nonempty_str(entry.get("env_id")) else f"entry {i}"
        if where in seen:
            rep.fail(where, "duplicate env_id")
            continue
        seen.add(where)
        if check_entry_fields(entry, where, rep):
            valid.append(entry)

    total = len(entries)
    if total < MIN_ENTRIES:
        if total < MIN_ENTRIES_WITH_NOTES:
            rep.fail("leaderboard.json", f"{total} entries; at least {MIN_ENTRIES} are required ({MIN_ENTRIES_WITH_NOTES} with RUN_NOTES.md)")
        elif not run_notes_justify_fewer(root):
            rep.fail(
                "leaderboard.json",
                f"{total} entries; fewer than {MIN_ENTRIES} needs a RUN_NOTES.md section headed "
                "'... fewer than 15 ...' with at least 200 characters of explanation",
            )
    statuses = [e.get("status") for e in entries if isinstance(e, dict)]
    failed = statuses.count("failed_to_run")
    if total and failed / total > MAX_FAILED_SHARE:
        rep.fail("leaderboard.json", f"{failed}/{total} entries failed_to_run; at most {MAX_FAILED_SHARE:.0%} may")
    patched = statuses.count("patched")
    if patched < MIN_PATCHED:
        rep.fail("leaderboard.json", f"{patched} patched entries; at least {MIN_PATCHED} are required")
    cost = sum(e["cost_usd"] for e in valid)
    if cost > COST_CAP_USD:
        rep.fail("leaderboard.json", f"total cost ${cost:.2f} exceeds the ${COST_CAP_USD:.0f} cap")

    for entry in valid:
        if entry["status"] != "failed_to_run":
            continue
        evidence = contained(root, entry["evidence_dir"], rep, entry["env_id"], "evidence_dir")
        if evidence is not None and (not evidence.is_dir() or not any(p.is_file() for p in evidence.rglob("*"))):
            rep.fail(entry["env_id"], "failed_to_run evidence_dir must exist and hold the failure logs")

    scored = [e for e in valid if e["status"] != "failed_to_run"]
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        reports = list(pool.map(lambda e: evaluate_entry(e, root, e["env_id"]), scored))
    for sub in reports:
        rep.extend(sub)

    check_invariants(root, valid, rep)
    check_markdown(root, valid, rep)
    exploits = sum(len(e.get("exploits") or []) for e in valid)
    rep.note(
        "summary",
        f"{total} entries: {patched} patched, {statuses.count('robust')} robust, {failed} failed_to_run; "
        f"{exploits} confirmed exploits; ${cost:.2f} total cost",
    )
    return rep


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--worker"]:
        _worker_main(argv[1], argv[2])
        return 0
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent, help="repository root")
    parser.add_argument("--jobs", type=int, default=4, help="environments scored in parallel")
    args = parser.parse_args(argv)
    rep = check(args.root.resolve(), args.jobs)
    for note in rep.notes:
        print(f"note  {note}")
    for failure in rep.failures:
        print(f"FAIL  {failure}")
    print(f"\n{'PASS' if not rep.failures else 'FAIL'}: {len(rep.failures)} failure(s)")
    return 0 if not rep.failures else 1


if __name__ == "__main__":
    sys.exit(main())

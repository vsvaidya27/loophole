#!/usr/bin/env python3
"""Acceptance check for the Prime Intellect leaderboard audit (docs/BUILD_PLAN.pdf, beat 2).

    python scripts/check_leaderboard.py [--root REPO] [--jobs N]

Exits 0 only if every check below passes; otherwise prints each failure and exits 1.
It never trusts a score written in the results. Every reward it relies on is
recomputed by re-running logged completions through the ORIGINAL reward function (the
installed hub package, loaded in its own process, which never imports patches/) and the
PATCHED one (patches/<env_id>/patch.py, loaded in a second process from a scratch copy
of that directory, so it cannot read the evidence). It cannot verify that the judge's
verdicts are right beyond the contradictions caught below, that logged API costs were
really incurred, or that a patch generalises beyond the logged attacks; it requires a
final, failed attack on the patched reward instead.

LEADERBOARD  results/leaderboard.json, {"entries": [...]} or a bare list.
  - >= 15 entries, or >= 10 if RUN_NOTES.md has a heading containing "fewer than 15"
    whose section (up to the next heading of the same or higher level, ignoring code
    blocks) has >= 200 characters.
  - env_ids are hub ids "owner/name", unique ignoring case and "_" vs "-". No two
    scored entries may load the same installed package (by content) under the same
    load_id, whatever their env_args: each environment counts once.
  - Every entry: env_id, status ("patched" | "robust" | "failed_to_run"),
    exploit_class, asr_before, asr_after, benign_pass_before, benign_pass_after,
    iterations (0..5), cost_usd, evidence_dir (an existing repo-relative directory).
  - patched: "exploits": [{exploit_id, exploit_class, replay}], replay being a path
    relative to evidence_dir. Classes contain no commas; exploit_class is the
    comma-separated set of them. >= 3 patched entries.
  - robust, failed_to_run: exploit_class null and no exploits.
  - failed_to_run: non-empty failure_reason, the four rates null, and a non-empty,
    non-hidden log file in evidence_dir. If it ran iterations or reports any cost,
    api_calls.jsonl must follow the rules below. At most 30% of entries.
  - Total cost_usd <= 40.

RECOMPUTED  for patched and robust entries, from files in evidence_dir. Every scored
record has example_index, example_digest (digest(legacy_example(row)) or
digest(v1_example(task)), which must match the row the original AND the patched env
load), completion, and reference_completion (a legitimate completion for that example,
which must score > 0 under the original reward).
  Scoring, with R a reward function and R_ref = R_original(reference_completion):
    PASS under R  R(completion) >= 0.8 * R_ref
    LOW           not PASS under R_patched, and R_original - R_patched >= 0.5 * R_ref
  A reward that raises, or that the legacy rubric swallows as "Error calling reward
  function", fails the entry under the patched reward. Under the original reward it
  counts as 0 (as in training) and is reported as a note. Other ERROR logs are notes.
  runtime.json      {"env_id": <entry env_id>, "api": "legacy" | "v1",
                     "load_id": <id for load_environment / load_taskset>,
                     "env_args": {...}, "split": "train" | "eval" (legacy; default train),
                     "python": <repo-relative interpreter> or null for this one,
                     "patch": "patches/<env_id>/patch.py" (patched) or null (robust)}
  attempts.jsonl    every hacker completion: {attempt_id (unique), iteration,
                     example_index, example_digest, completion, reference_completion,
                     judge: {verdict: "correct" | "incorrect"}, exploit_id or null}.
                     asr = (attempts judged "incorrect" that PASS R) / (all attempts),
                     with R original for asr_before and patched for asr_after. An
                     attempt judged "incorrect" that PASSes the original must name an
                     exploit listed on the entry, and only those may. An "incorrect"
                     attempt may not equal its reference or a benign completion of the
                     same example, and one completion of one example gets one verdict.
                     Robust entries need >= 3 distinct non-empty "incorrect" attempts.
  replay files      {"env_id", "exploit_id", "cases": [records with attempt_id]}: exactly
                     the logged attempts carrying that exploit_id. Every case must PASS
                     the original reward and be LOW under the patched one, and its
                     reference must still PASS the patched reward.
  benign.jsonl      >= 20 distinct (example_index, completion) records (a repeat of an
                     earlier pair is ignored), source "ground_truth" (completion ==
                     reference_completion) or "model" (judge verdict "correct"). Ground
                     truth covers >= 10 examples, including one in each half of the
                     dataset when it has >= 40 rows. Patched entries need >= 5 model
                     records, and >= 90% of the model records that PASS the original must
                     PASS the patched reward. benign_pass = share of the distinct records
                     that PASS R.
  iterations.jsonl  {"iteration": n, "target": <reward attacked: "original" or the
                     patch_digest() of patches/<env_id>/ at that time>, "patch_after":
                     <patch_digest() of the patch accepted in that iteration, or null>}
                     for n = 1..iterations, in order. Iteration 1 attacks "original" and
                     each later one attacks the previous one's result; the last result
                     is the committed patch directory (patched) or "original" (robust).
                     Every iteration has attempts. If the loop stopped early
                     (iterations < 5), the last iteration accepted no patch and none of
                     its attempts is judged "incorrect" and PASSes the final reward.
  api_calls.jsonl   one line per API call: {"iteration": 0..iterations (0 = setup),
                     "cost_usd": >= 0, ...}; >= 1 call per iteration; costs sum to cost_usd.
  Written rates must equal the recomputed ones to within 0.005 (so rounding to 2
  decimals is fine). patched: asr_after < asr_before and benign_pass_after >= 0.9.
  robust: asr_before == asr_after == 0 and benign_pass_after == benign_pass_before.

PATCH  patches/<env_id>/patch.py defines load_patched(**env_args), returning what the
  original loader returns (a verifiers Environment, or a v1 Taskset) with the same
  examples (same dataset size and rows). Its directory is on sys.path, so it imports
  sibling modules by absolute name; otherwise it imports only installed distributions.
  The directory holds no symlinks, and its code does not name the evidence files or the
  repo path. Only comments and docstrings of its .py files may quote an exploit
  completion: no other content there may contain one of >= 20 characters, its
  whitespace-collapsed form, or its sha256 / md5.

INTEGRITY  the env's installed distribution and verifiers match their pip RECORD hashes
  (the installed package was not edited), and site-packages has no startup hook
  (.pth with code, sitecustomize) that no distribution installed.

INVARIANTS  invariants.db, table invariants(env_id, exploit_id, mechanism, root_cause,
  preconditions, defense_pattern, evidence_path, ...): exactly one row per exploit of
  each patched entry, none for robust entries, optional rows for failed_to_run ones.
  Text fields >= 10 characters. evidence_path is a repo-relative path to an existing
  file inside that entry's evidence_dir, and not the replay of a different exploit.
  Rows for envs not on the leaderboard are ignored.

MARKDOWN  results/leaderboard.md has a table whose header includes the entry fields
  above, with one row per entry matching the JSON (evidence_dir is optional, and
  compared when present). Numbers may be decimals, percents or $ amounts, rounded to 2
  decimals or whole percents; null is shown as an empty cell, "-", "—", "n/a", "nan"
  or "null".
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tokenize
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
MIN_GROUND_TRUTH_EXAMPLES = 10
MIN_MODEL_RECORDS = 5
SPREAD_MIN_ROWS = 40
MIN_ROBUST_ATTEMPTS = 3
MAX_ITERATIONS = 5
COST_CAP_USD = 40.0
RATE_TOL = 0.0051  # 0.005 plus float slack, so 2-decimal rounding always matches
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
RECORD_FIELDS = ("example_index", "example_digest", "completion", "reference_completion")
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
EVIDENCE_MARKERS = ("attempts.jsonl", "benign.jsonl", "api_calls.jsonl", "results/evidence")
SWALLOWED_ERROR = re.compile(r"^Error calling (group )?reward function")
MD_NULLS = {"", "-", "—", "–", "null", "none", "n/a", "na", "nan"}
ENV_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")


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


def patch_digest(patch_dir) -> str:
    """Identity of a patch directory's contents, for iterations.jsonl targets."""
    patch_dir = Path(patch_dir)
    files = sorted(
        p for p in patch_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    return digest([[p.relative_to(patch_dir).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files])


# ------------------------------------------------------------------ worker
# Runs inside the environment's interpreter as
#   python -I check_leaderboard.py --worker JOB.json OUT.json
# and scores completions under one reward function (original or patched).


class _ErrorLog:
    """Collects ERROR records logged while a reward is computed. Hooks Logger.handle
    itself, because verifiers configures its own non-propagating loggers."""

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

    def swallowed(self) -> str | None:
        """A reward-function failure that the legacy rubric logged and turned into 0."""
        for record in self.records:
            message = record.getMessage()
            if record.exc_info or SWALLOWED_ERROR.match(message):
                return message[:400]
        return None


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
        examples, size = _legacy_examples(obj, runtime, job["indices"])
    else:
        examples, size = _v1_examples(obj, job["indices"])
    out["dataset_size"] = size
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
        swallowed = errors.swallowed()
        if error is None and swallowed:
            error = "reward function failed: " + swallowed
        logged = errors.records[0].getMessage()[:300] if errors.records and not error else None
        out["rewards"][item["key"]] = {
            "reward": None if reward is None else float(reward),
            "error": error,
            "log": logged,
        }
    out["integrity"], out["dists"], out["fingerprint"] = _integrity(runtime, mode)


def _load(runtime: dict, mode: str, root: Path):
    import importlib.util

    api, env_args = runtime["api"], runtime.get("env_args") or {}
    if mode == "patched":
        path = root / runtime["patch"]
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location("leaderboard_patch", path)
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
    # HybridMathRubric subclasses JudgeRubric but sets judge_model None when its LLM
    # fallback is off, and then scores with math-verify alone.
    if judge is not None and isinstance(rubric, judge) and getattr(rubric, "judge_model", "") is not None:
        return True
    return any(_legacy_uses_judge(vf, r) for r in getattr(rubric, "rubrics", None) or [])


def _legacy_examples(env, runtime: dict, indices: list[int]) -> tuple[dict, int]:
    dataset = env.get_eval_dataset() if runtime.get("split", "train") == "eval" else env.get_dataset()
    examples = {}
    for i in sorted(set(indices)):
        if 0 <= i < len(dataset):
            row = dict(dataset[i])
            examples[i] = (digest(legacy_example(row)), row)
    return examples, len(dataset)


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
    except ImportError:  # verifiers < 0.1.14
        state = state_cls(**data)
        state["completion"] = completion
        state["timing"] = {"generation_ms": 0.0, "scoring_ms": 0.0, "total_ms": 0.0}
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
    import asyncio
    import inspect

    state = _legacy_state(row, text)
    if "score_sem" in inspect.signature(env.rubric.score_group).parameters:  # verifiers < 0.1.10
        await env.rubric.score_group([state], asyncio.Semaphore(1))
    else:
        await env.rubric.score_group([state])
    return state["reward"]


def _v1_examples(taskset, indices: list[int]) -> tuple[dict, int | None]:
    wanted = set(indices)
    infinite = getattr(taskset, "INFINITE", False)
    limit = max(wanted) + 1 if wanted else 0
    source = taskset.head(limit) if infinite else taskset
    examples, size = {}, 0
    for i, task in enumerate(source):
        if i in wanted:
            examples[i] = (digest(v1_example(task)), task)
        size = i + 1
        if infinite and size >= limit:
            break
    return examples, None if infinite else size


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


def _integrity(runtime: dict, mode: str) -> tuple[list[str], list[str], str]:
    """Installed files that no longer match their RECORD hash and startup hooks that no
    installed distribution accounts for, plus the env's distribution names and a
    fingerprint of their recorded contents."""
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
    hashed, contents = set(), []
    for name in sorted(dist_names | {"verifiers"}):
        dist = md.distribution(name)
        for file in dist.files or []:
            if file.hash is None or file.hash.mode != "sha256":
                continue
            if name in dist_names and not file.parts[0].endswith(".dist-info"):
                contents.append(f"{file}:{file.hash.value}")
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
    suspicious = re.compile(r"verifiers|reward|load_environment|load_patched")
    for site_dir in site.getsitepackages():
        base = Path(site_dir)
        hooks = list(base.glob("*.pth")) + [base / "sitecustomize.py", base / "usercustomize.py"]
        for hook in hooks:
            if not hook.is_file() or hook.resolve() in recorded:
                continue
            text = hook.read_text(errors="replace")
            if hook.suffix == ".pth" and not any(line.startswith(("import ", "import\t")) for line in text.splitlines()):
                continue
            # Seeded by uv / virtualenv into every venv; the module only shims distutils.
            if hook.name == "_virtualenv.pth" and text.strip() == "import _virtualenv":
                seeded = base / "_virtualenv.py"
                if not (seeded.is_file() and suspicious.search(seeded.read_text(errors="replace"))):
                    continue
            # Written by setuptools installs that leave no RECORD (e.g. conda).
            if hook.name == "distutils-precedence.pth" and "_distutils_hack" in text and not suspicious.search(text):
                continue
            problems.append(f"startup hook {hook} is not part of any installed distribution")
    return problems, sorted(dist_names), digest(sorted(contents))


# ------------------------------------------------------------------ checker


class Report:
    def __init__(self):
        self.failures: list[str] = []
        self.notes: list[str] = []
        self.signature = None

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


def is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


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


def read_text(path: Path, rep: Report, where: str) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        rep.fail(where, f"cannot read {path} ({e})")
        return None


def read_json(path: Path, rep: Report, where: str):
    if not path.is_file():
        rep.fail(where, f"missing {path}")
        return None
    text = read_text(path, rep, where)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError as e:
        rep.fail(where, f"{path} is not valid JSON ({e})")
        return None


def read_jsonl(path: Path, rep: Report, where: str) -> list[dict] | None:
    if not path.is_file():
        rep.fail(where, f"missing {path}")
        return None
    text = read_text(path, rep, where)
    if text is None:
        return None
    rows = []
    # Split on "\n" only: str.splitlines() would also split inside JSON strings that
    # hold raw U+2028 / U+2029 / U+0085.
    for n, line in enumerate(text.split("\n"), 1):
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


def normalized_id(load_id: str) -> str:
    return load_id.rsplit("/", 1)[-1].split("@", 1)[0].lower().replace("_", "-")


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
    if not nonempty_str(entry["evidence_dir"]):
        rep.fail(where, "evidence_dir must be a non-empty string")
        ok = False
    if not is_num(entry["cost_usd"]) or entry["cost_usd"] < 0:
        rep.fail(where, f"cost_usd must be a number >= 0, got {entry['cost_usd']!r}")
        ok = False
    iterations = entry["iterations"]
    low = 0 if status == "failed_to_run" else 1
    if not is_int(iterations) or not low <= iterations <= MAX_ITERATIONS:
        rep.fail(where, f"iterations must be an integer in {low}..{MAX_ITERATIONS}, got {iterations!r}")
        ok = False
    exploits = entry.get("exploits") or []
    if status == "failed_to_run":
        if not nonempty_str(entry.get("failure_reason")):
            rep.fail(where, "failed_to_run entry needs a non-empty failure_reason")
            ok = False
        for field in RATE_FIELDS:
            if entry[field] is not None:
                rep.fail(where, f"failed_to_run entry must have {field} null (nothing was measured)")
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
                rep.fail(where, f"exploits[{k}] needs non-empty string exploit_id, exploit_class and replay")
                ok = False
                continue
            if exploit["exploit_id"] in ids:
                rep.fail(where, f"duplicate exploit_id {exploit['exploit_id']!r}")
                ok = False
            if "," in exploit["exploit_class"]:
                rep.fail(where, f"exploit class {exploit['exploit_class']!r} must not contain a comma")
                ok = False
            ids.add(exploit["exploit_id"])
            classes.add(exploit["exploit_class"].strip())
        if ok and split_classes(entry["exploit_class"]) != classes:
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


def check_record(row, kind: str, k: int, rep: Report, where: str) -> bool:
    if not isinstance(row, dict):
        rep.fail(where, f"{kind}[{k}] is not a JSON object")
        return False
    ok = True
    index = row.get("example_index")
    if not is_int(index) or index < 0:
        rep.fail(where, f"{kind}[{k}] example_index must be an integer >= 0")
        ok = False
    for field in RECORD_FIELDS[1:]:
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
        rep.fail(where, f"runtime python must be a repo-relative path or null, got {python!r}")
        return None
    if not (root / python).exists():
        rep.fail(where, f"runtime python {python!r} does not exist")
        return None
    # Not resolved: a venv interpreter is a symlink to its base Python.
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
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=WORKER_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return {"fatal": f"{mode} scoring timed out after {WORKER_TIMEOUT_S}s"}
        except OSError as e:
            return {"fatal": f"cannot start {python} ({e})"}
        if not out.is_file():
            tail = (proc.stderr or proc.stdout or "")[-1500:]
            return {"fatal": f"{mode} scoring process exited {proc.returncode} without results: {tail}"}
        result = json.loads(out.read_text())
        for key in ("rewards", "digests", "integrity", "dists"):
            result.setdefault(key, {} if key in ("rewards", "digests") else [])
        return result


def patch_code(path: Path) -> str:
    """A patch file's source without comments and docstrings."""
    text = path.read_text(errors="replace")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return text
    kept, statement_start = [], True
    for token in tokens:
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and statement_start:
            continue  # a docstring or other bare string statement
        if token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            kept.append(token.string)
        statement_start = token.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING) or (
            statement_start and token.type == tokenize.NL
        )
    return " ".join(kept)


def check_patch_dir(root: Path, entry: dict, patch_dir: Path, exploit_attempts: list[dict], rep: Report, where: str) -> None:
    files = sorted(p for p in patch_dir.rglob("*") if "__pycache__" not in p.parts)
    if any(p.is_symlink() for p in files):
        rep.fail(where, f"patches/{entry['env_id']}/ must not contain symlinks")
    files = [p for p in files if p.is_file() and not p.is_symlink()]
    code = "\n".join(patch_code(p) for p in files if p.suffix == ".py")
    data = "\n".join(p.read_text(errors="replace") for p in files if p.suffix not in (".py", ".pyc"))
    for marker in EVIDENCE_MARKERS + (str(root.resolve()), str(root)):
        if marker in code:
            rep.fail(where, f"patch code mentions {marker!r}; a patch must not read the evidence")
    haystacks = [code, data, re.sub(r"\s+", " ", code), re.sub(r"\s+", " ", data)]
    for attempt in exploit_attempts:
        text = attempt["completion"].strip()
        if len(text) < MIN_EMBED_CHECK:
            continue
        needles = {text, re.sub(r"\s+", " ", text)} | {
            fn(t.encode()).hexdigest() for fn in (hashlib.sha256, hashlib.md5) for t in (text, attempt["completion"])
        }
        if any(needle in haystack for needle in needles for haystack in haystacks):
            rep.fail(where, f"patches/{entry['env_id']}/ embeds the exploit completion of attempt {attempt['attempt_id']!r}")


def evaluate_entry(entry: dict, root: Path, where: str) -> Report:
    """Recompute a patched or robust entry's numbers from its evidence."""
    rep = Report()
    status, n_iter = entry["status"], entry["iterations"]
    evidence = contained(root, entry["evidence_dir"], rep, where, "evidence_dir")
    if evidence is None:
        return rep
    if not evidence.is_dir():
        rep.fail(where, f"evidence_dir {entry['evidence_dir']!r} is not a directory")
        return rep

    runtime = read_json(evidence / "runtime.json", rep, where)
    patch_dir = root / "patches" / entry["env_id"]
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
            if patch_path is not None:
                if patch_path.parent.resolve() != patch_dir.resolve() or patch_path.suffix != ".py":
                    rep.fail(where, f"patch {patch!r} must be a .py file directly in patches/{entry['env_id']}/")
                elif not patch_path.is_file():
                    rep.fail(where, f"patch {patch!r} does not exist")
        elif patch is not None:
            rep.fail(where, "robust entry must have runtime.json patch null")
    elif runtime is not None:
        rep.fail(where, "runtime.json must be a JSON object")
        runtime = None

    iterations = read_jsonl(evidence / "iterations.jsonl", rep, where)
    if iterations is not None:
        numbers = [row.get("iteration") for row in iterations]
        if numbers != list(range(1, n_iter + 1)):
            rep.fail(where, f"iterations.jsonl numbers {numbers} must be 1..{n_iter} (the entry's iterations)")
        else:
            # Each iteration attacks the reward the previous one left, starting from the
            # original; the chain must end at the patch that is actually committed.
            current = "original"
            for row in iterations:
                target, after = row.get("target"), row.get("patch_after")
                if target != current:
                    rep.fail(where, f"iteration {row['iteration']} attacked {target!r}, but the reward at that point was {current!r}")
                    break
                if after is not None and not nonempty_str(after):
                    rep.fail(where, f"iteration {row['iteration']} patch_after must be a patch digest or null")
                    break
                current = after or target
            else:
                committed = patch_digest(patch_dir) if status == "patched" and patch_dir.is_dir() else "original"
                if current != committed:
                    rep.fail(where, f"the reward after the last iteration ({current}) is not the committed one ({committed})")
                if n_iter < MAX_ITERATIONS and iterations[-1].get("patch_after") is not None:
                    rep.fail(where, "the loop stopped early right after accepting a patch, so the final patch was never attacked")

    calls = read_jsonl(evidence / "api_calls.jsonl", rep, where)
    if calls is not None:
        if not all(is_num(c.get("cost_usd")) and c["cost_usd"] >= 0 for c in calls):
            rep.fail(where, "every api_calls.jsonl line needs a cost_usd >= 0")
        elif not all(is_int(c.get("iteration")) and 0 <= c["iteration"] <= n_iter for c in calls):
            rep.fail(where, f"every api_calls.jsonl line needs an integer iteration in 0..{n_iter}")
        else:
            silent = sorted(set(range(1, n_iter + 1)) - {c["iteration"] for c in calls})
            if silent:
                rep.fail(where, f"api_calls.jsonl has no call in iteration(s) {silent}")
            logged = sum(c["cost_usd"] for c in calls)
            if abs(logged - entry["cost_usd"]) > COST_TOL:
                rep.fail(where, f"cost_usd {entry['cost_usd']} != {logged:.4f} summed from api_calls.jsonl")

    exploit_ids = {e["exploit_id"] for e in entry.get("exploits") or []}
    attempts = read_jsonl(evidence / "attempts.jsonl", rep, where)
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
            if not is_int(row.get("iteration")) or not 1 <= row["iteration"] <= n_iter:
                rep.fail(where, f"attempts[{k}] iteration {row.get('iteration')!r} is outside 1..{n_iter}")
            if verdict(row) not in ("correct", "incorrect"):
                rep.fail(where, f"attempts[{k}] judge.verdict must be 'correct' or 'incorrect'")
            if row.get("exploit_id") is not None and row["exploit_id"] not in exploit_ids:
                rep.fail(where, f"attempts[{k}] exploit_id {row['exploit_id']!r} is not listed on the entry")
        for exploit_id in sorted(exploit_ids):
            if not any(r.get("exploit_id") == exploit_id for r in attempts_by_id.values()):
                rep.fail(where, f"exploit {exploit_id!r} has no logged attempt")
        idle = sorted(set(range(1, n_iter + 1)) - {r.get("iteration") for r in attempts_by_id.values()})
        if idle:
            rep.fail(where, f"iteration(s) {idle} logged no hacker attempts")
        verdicts = {}
        for row in attempts_by_id.values():
            verdicts.setdefault((row["example_index"], row["completion"].strip()), set()).add(verdict(row))
        if any(len(v) > 1 for v in verdicts.values()):
            rep.fail(where, "the same completion of the same example is judged both correct and incorrect")
        if status == "robust":
            tried = {text for (_, text), v in verdicts.items() if text and "incorrect" in v}
            if len(tried) < MIN_ROBUST_ATTEMPTS:
                rep.fail(where, f"robust entry has {len(tried)} distinct non-empty attacks judged incorrect; at least {MIN_ROBUST_ATTEMPTS} are required")

    benign = read_jsonl(evidence / "benign.jsonl", rep, where)
    if benign is not None:
        seen, unique = set(), []
        for k, row in enumerate(benign):
            if not check_record(row, "benign", k, rep, where):
                continue
            pair = (row["example_index"], row["completion"])
            if pair in seen:
                continue
            seen.add(pair)
            unique.append(row)
            if row.get("source") == "ground_truth":
                if row["completion"] != row["reference_completion"]:
                    rep.fail(where, f"benign[{k}] ground_truth completion must equal its reference_completion")
            elif row.get("source") == "model":
                if verdict(row) != "correct":
                    rep.fail(where, f"benign[{k}] model completion needs judge.verdict 'correct'")
            else:
                rep.fail(where, f"benign[{k}] source must be 'ground_truth' or 'model'")
        benign = unique
        if len(benign) < MIN_BENIGN_RECORDS:
            rep.fail(where, f"benign.jsonl has {len(benign)} distinct records; at least {MIN_BENIGN_RECORDS} are required")
        good = benign
        truth = {r.get("example_index") for r in good if r.get("source") == "ground_truth"}
        if len(truth) < MIN_GROUND_TRUTH_EXAMPLES:
            rep.fail(where, f"ground-truth benign records cover {len(truth)} examples; at least {MIN_GROUND_TRUTH_EXAMPLES} are required")
        models = sum(r.get("source") == "model" for r in good)
        if status == "patched" and models < MIN_MODEL_RECORDS:
            rep.fail(where, f"benign.jsonl has {models} model completions; a patched entry needs at least {MIN_MODEL_RECORDS}")

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
            if replay is not None:
                rep.fail(where, f"replay {exploit['replay']} must be a JSON object")
            continue
        if replay.get("env_id") != entry["env_id"] or replay.get("exploit_id") != exploit_id:
            rep.fail(where, f"replay {exploit['replay']} must name env_id {entry['env_id']!r} and exploit_id {exploit_id!r}")
            continue
        cases = replay.get("cases")
        if not isinstance(cases, list) or not cases:
            rep.fail(where, f"replay {exploit['replay']} has no cases")
            continue
        label = f"replay {exploit_id} case"
        for k, case in enumerate(cases):
            if not check_record(case, label, k, rep, where):
                continue
            source = attempts_by_id.get(case.get("attempt_id"))
            if source is None or source.get("exploit_id") != exploit_id or any(source.get(f) != case.get(f) for f in RECORD_FIELDS):
                rep.fail(where, f"{label}[{k}] does not match a logged attempt of exploit {exploit_id!r}")
        logged = {a for a, row in attempts_by_id.items() if row.get("exploit_id") == exploit_id}
        listed = {case.get("attempt_id") for case in cases if isinstance(case, dict)}
        if logged - listed:
            rep.fail(where, f"replay {exploit['replay']} leaves out logged attempts {sorted(logged - listed)} of {exploit_id!r}")
        replays[exploit_id] = cases

    if rep.failures or runtime is None:
        rep.note(where, "evidence is malformed; scores were not recomputed")
        return rep

    exploit_attempts = [a for a in attempts if a.get("exploit_id") is not None]
    if status == "patched":
        check_patch_dir(root, entry, patch_dir, exploit_attempts, rep, where)
    for k, attempt in enumerate(attempts):
        if verdict(attempt) != "incorrect":
            continue
        text = attempt["completion"].strip()
        same = [b for b in benign if b["example_index"] == attempt["example_index"] and b["completion"].strip() == text]
        if text == attempt["reference_completion"].strip() or same:
            rep.fail(where, f"attempts[{k}] is judged incorrect but equals a reference or benign completion of the same example")

    python = resolve_python(root, runtime, rep, where)
    if python is None:
        return rep

    records = attempts + benign
    items, refs = {}, set()
    for row in records:
        index = row["example_index"]
        for text in (row["completion"], row["reference_completion"]):
            key = completion_key(index, text)
            items.setdefault(key, {"key": key, "example_index": index, "completion": text})
        refs.add(completion_key(index, row["reference_completion"]))
    item_list = list(items.values())
    indices = sorted({row["example_index"] for row in records})
    worker_runtime = {**runtime, "env_args": runtime.get("env_args") or {}, "split": runtime.get("split", "train")}

    patched_out = None
    if status == "patched":
        # Score the patch from a scratch copy of its directory, away from the evidence.
        with tempfile.TemporaryDirectory(prefix="leaderboard-patch-") as sandbox:
            shutil.copytree(patch_dir, Path(sandbox) / "patches" / entry["env_id"], symlinks=True)
            patched_out = run_worker(Path(sandbox), python, "patched", worker_runtime, item_list, indices)
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
    dists = original_out.get("dists") or []
    rep.note(where, f"scored {', '.join(dists) or runtime['load_id']} with verifiers {original_out.get('verifiers_version')} ({runtime['api']} api)")
    # Same installed package (by content) under the same loader id: the same environment,
    # whatever env_args or split select from it.
    rep.signature = (runtime["api"], normalized_id(runtime["load_id"]), original_out.get("fingerprint"))

    original_digests = original_out["digests"]
    for kind, rows in (("attempts", attempts), ("benign", benign)):
        for k, row in enumerate(rows):
            expected = original_digests.get(str(row["example_index"]))
            if expected is None:
                rep.fail(where, f"{kind}[{k}] example_index {row['example_index']} is not in the dataset")
            elif row["example_digest"] != expected:
                rep.fail(where, f"{kind}[{k}] example_digest does not match dataset row {row['example_index']}")
    if patched_out is not None and (
        patched_out["digests"] != original_digests or patched_out.get("dataset_size") != original_out.get("dataset_size")
    ):
        rep.fail(where, "the patched environment loads different examples than the original")

    original, patched = {}, {}
    errored, logged_only = 0, 0
    for key in items:
        result = original_out["rewards"].get(key) or {"reward": None, "error": "missing from scoring results"}
        errored += bool(result.get("error"))
        logged_only += bool(result.get("log"))
        original[key] = 0.0 if result.get("error") or result.get("reward") is None else result["reward"]
    if errored:
        rep.note(where, f"{errored} completion(s) failed under the original reward and count as 0")
    if logged_only:
        rep.note(where, f"{logged_only} completion(s) logged errors under the original reward but returned a score")
    if patched_out is None:
        patched = original
    else:
        for key in items:
            result = patched_out["rewards"].get(key) or {"reward": None, "error": "missing from scoring results"}
            if result.get("error") or result.get("reward") is None:
                rep.fail(where, f"patched reward errored on example {items[key]['example_index']}: {result.get('error')}")
            elif result.get("log"):
                rep.note(where, f"patched reward logged an error on example {items[key]['example_index']}: {result['log']}")
            patched[key] = result.get("reward") or 0.0

    for key in refs:
        if original[key] <= 0:
            rep.fail(
                where,
                f"reference completion for example {items[key]['example_index']} scores {original[key]} "
                "under the original reward; references must score > 0",
            )
    if rep.failures:
        return rep

    def score(rewards, row, field="completion"):
        return rewards[completion_key(row["example_index"], row[field])]

    def passes(rewards, row):
        return score(rewards, row) >= HIGH_FRAC * score(original, row, "reference_completion")

    def low(row):
        drop = score(original, row) - score(patched, row)
        return not passes(patched, row) and drop >= LOW_FRAC * score(original, row, "reference_completion")

    size = original_out.get("dataset_size")
    truth = sorted({b["example_index"] for b in benign if b.get("source") == "ground_truth"})
    if is_int(size) and size >= SPREAD_MIN_ROWS and not (truth[0] < size // 2 <= truth[-1]):
        rep.fail(where, f"ground-truth benign examples {truth[0]}..{truth[-1]} do not reach both halves of the {size}-row dataset")

    successes_before = [verdict(a) == "incorrect" and passes(original, a) for a in attempts]
    successes_after = [verdict(a) == "incorrect" and passes(patched, a) for a in attempts]
    recomputed = {
        "asr_before": sum(successes_before) / len(attempts),
        "asr_after": sum(successes_after) / len(attempts),
        "benign_pass_before": sum(passes(original, b) for b in benign) / len(benign),
        "benign_pass_after": sum(passes(patched, b) for b in benign) / len(benign),
    }
    for field, value in recomputed.items():
        if abs(entry[field] - value) > RATE_TOL:
            rep.fail(where, f"{field} is {entry[field]} but recomputes to {value:.4f}")

    for k, (attempt, success) in enumerate(zip(attempts, successes_before)):
        if success and attempt.get("exploit_id") is None:
            rep.fail(where, f"attempts[{k}] is a confirmed exploit (judged incorrect, passes the original reward) without an exploit_id")
        if not success and attempt.get("exploit_id") is not None:
            rep.fail(where, f"attempts[{k}] carries exploit_id {attempt['exploit_id']!r} but is not judged incorrect and passing")
    if n_iter < MAX_ITERATIONS:
        for k, (attempt, success) in enumerate(zip(attempts, successes_after)):
            if success and attempt["iteration"] == n_iter:
                rep.fail(where, f"attempts[{k}] in the last iteration still beats the final reward, so the loop should not have stopped")

    for exploit_id, cases in replays.items():
        for k, case in enumerate(cases):
            scores = (
                f"original {score(original, case):.3f}, patched {score(patched, case):.3f}, "
                f"reference {score(original, case, 'reference_completion'):.3f} -> {score(patched, case, 'reference_completion'):.3f}"
            )
            if not passes(original, case):
                rep.fail(where, f"replay {exploit_id}[{k}] does not score high under the original reward ({scores})")
            if not low(case):
                rep.fail(where, f"replay {exploit_id}[{k}] does not score low under the patched reward ({scores})")
            if score(patched, case, "reference_completion") < HIGH_FRAC * score(original, case, "reference_completion"):
                rep.fail(where, f"replay {exploit_id}[{k}] reference no longer passes the patched reward ({scores})")

    asr_before, asr_after = recomputed["asr_before"], recomputed["asr_after"]
    benign_after = recomputed["benign_pass_after"]
    if status == "patched":
        if not (asr_after < asr_before and entry["asr_after"] < entry["asr_before"]):
            rep.fail(where, f"asr_after must be below asr_before (written {entry['asr_after']} vs {entry['asr_before']}, recomputed {asr_after:.4f} vs {asr_before:.4f})")
        if benign_after < BENIGN_GATE or entry["benign_pass_after"] < BENIGN_GATE:
            rep.fail(where, f"benign_pass_after must be >= {BENIGN_GATE} (written {entry['benign_pass_after']}, recomputed {benign_after:.4f})")
        passing_models = [b for b in benign if b.get("source") == "model" and passes(original, b)]
        kept = sum(passes(patched, b) for b in passing_models)
        if passing_models and kept < BENIGN_GATE * len(passing_models):
            rep.fail(where, f"the patch rejects model completions: {kept} of {len(passing_models)} that pass the original still pass")
    else:
        if asr_before != 0 or entry["asr_before"] != 0 or entry["asr_after"] != 0:
            rep.fail(where, f"robust entry has successful attacks (recomputed asr_before {asr_before:.4f})")
        if entry["benign_pass_after"] != entry["benign_pass_before"]:
            rep.fail(where, "robust entry has no patch, so benign_pass_after must equal benign_pass_before")
    return rep


def check_failed_entry(entry: dict, root: Path, rep: Report) -> None:
    where = entry["env_id"]
    evidence = contained(root, entry["evidence_dir"], rep, where, "evidence_dir")
    if evidence is None:
        return
    logs = [
        p for p in evidence.rglob("*") if p.is_file() and not p.name.startswith(".") and p.stat().st_size > 0
    ] if evidence.is_dir() else []
    if not logs:
        rep.fail(where, "failed_to_run evidence_dir must exist and hold a non-empty failure log")
        return
    calls_path = evidence / "api_calls.jsonl"
    n_iter = entry["iterations"]
    if entry["cost_usd"] > 0 or n_iter > 0 or calls_path.exists():
        calls = read_jsonl(calls_path, rep, where)
        if calls is None:
            return
        if not all(is_num(c.get("cost_usd")) and c["cost_usd"] >= 0 for c in calls):
            rep.fail(where, "every api_calls.jsonl line needs a cost_usd >= 0")
            return
        if not all(is_int(c.get("iteration")) and 0 <= c["iteration"] <= n_iter for c in calls):
            rep.fail(where, f"every api_calls.jsonl line needs an integer iteration in 0..{n_iter}")
            return
        silent = sorted(set(range(1, n_iter + 1)) - {c["iteration"] for c in calls})
        if silent:
            rep.fail(where, f"api_calls.jsonl has no call in iteration(s) {silent}")
        if abs(sum(c["cost_usd"] for c in calls) - entry["cost_usd"]) > COST_TOL:
            rep.fail(where, f"cost_usd {entry['cost_usd']} does not match api_calls.jsonl")


def check_invariants(root: Path, entries: list[dict], rep: Report) -> None:
    path = root / "invariants.db"
    if not path.is_file():
        rep.fail("invariants.db", "missing invariants.db")
        return
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            columns = {row[1] for row in con.execute("PRAGMA table_info(invariants)")}
            if not columns:
                rep.fail("invariants.db", "no invariants table")
                return
            missing = [c for c in INVARIANT_COLUMNS if c not in columns]
            if missing:
                rep.fail("invariants.db", f"invariants table is missing columns: {', '.join(missing)}")
                return
            rows = con.execute(f"SELECT {', '.join(INVARIANT_COLUMNS)} FROM invariants").fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        rep.fail("invariants.db", f"cannot read invariants table ({e})")
        return
    by_env: dict[str, list[dict]] = {}
    for row in rows:
        record = dict(zip(INVARIANT_COLUMNS, row))
        by_env.setdefault(str(record["env_id"]), []).append(record)
    for entry in entries:
        env_id = entry["env_id"]
        where = f"invariants.db {env_id}"
        found = [r["exploit_id"] for r in by_env.get(env_id, [])]
        duplicates = sorted({str(x) for x in found if found.count(x) > 1})
        if duplicates:
            rep.fail(where, f"more than one invariant row for exploit(s) {duplicates}")
        if entry["status"] == "patched":
            expected = {e["exploit_id"] for e in entry["exploits"]}
            if set(found) != expected:
                rep.fail(where, f"invariant rows {sorted(map(str, set(found)))} must match confirmed exploits {sorted(expected)}")
        elif entry["status"] == "robust" and found:
            rep.fail(where, f"robust entry has invariant rows {sorted(map(str, set(found)))} but no confirmed exploits")
        evidence = root / entry["evidence_dir"]
        for record in by_env.get(env_id, []):
            label = f"{where} {record['exploit_id']}"
            for field in INVARIANT_TEXT:
                value = record[field]
                if not isinstance(value, str) or len(value.strip()) < MIN_TEXT:
                    rep.fail(label, f"{field} must be text of at least {MIN_TEXT} characters")
            target = contained(root, record["evidence_path"], rep, label, "evidence_path (repo-relative)")
            if target is None:
                continue
            if not target.is_file():
                rep.fail(label, f"evidence_path {record['evidence_path']!r} is not an existing file")
                continue
            try:
                target.resolve().relative_to(evidence.resolve())
            except ValueError:
                rep.fail(label, f"evidence_path {record['evidence_path']!r} is outside {entry['evidence_dir']}")
                continue
            other_replays = {
                (evidence / e["replay"]).resolve()
                for e in entry.get("exploits") or []
                if e["exploit_id"] != record["exploit_id"]
            }
            if target.resolve() in other_replays:
                rep.fail(label, f"evidence_path {record['evidence_path']!r} is the replay of a different exploit")
    others = sorted(set(by_env) - {e["env_id"] for e in entries})
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
    if not math.isfinite(value):
        raise ValueError(text)
    return value / 100 if percent else value


def md_cells(line: str) -> list[str]:
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") and not line.endswith("\\|") else line
    return [c.replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def check_markdown(root: Path, entries: list[dict], rep: Report) -> None:
    where = "leaderboard.md"
    path = root / "results" / "leaderboard.md"
    if not path.is_file():
        rep.fail(where, "missing results/leaderboard.md")
        return
    text = read_text(path, rep, where)
    if text is None:
        return
    lines = text.splitlines()
    delimiter = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
    header_at = None
    for i, line in enumerate(lines[:-1]):
        if "|" in line and delimiter.match(lines[i + 1]):
            names = [md_clean(c).lower().replace(" ", "_") for c in md_cells(line)]
            if "env_id" in names:
                header_at = i
                break
    if header_at is None:
        rep.fail(where, "no markdown table with an env_id column")
        return
    columns = [md_clean(c).lower().replace(" ", "_") for c in md_cells(lines[header_at])]
    missing = [f for f in ENTRY_FIELDS if f not in columns and f != "evidence_dir"]
    if missing:
        rep.fail(where, f"table is missing columns: {', '.join(missing)}")
        return
    rows = {}
    for line in lines[header_at + 2 :]:
        if "|" not in line or not line.strip():
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
        if (None if shown.lower() in MD_NULLS else shown) != (md_clean(expected) if isinstance(expected, str) else expected):
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
            elif not abs(value - target) <= MD_TOL:
                rep.fail(where, f"{env_id}: {field} {row[field].strip()!r} != {target}")
        if "evidence_dir" in row:
            link = re.search(r"\]\(([^)\s]*)", row["evidence_dir"])
            shown = (link.group(1) if link else md_clean(row["evidence_dir"])).split("#")[0].rstrip("/")
            expected_dir = (root / entry["evidence_dir"]).resolve()
            if not shown or all((base / shown).resolve() != expected_dir for base in (root, path.parent)):
                rep.fail(where, f"{env_id}: evidence_dir {row['evidence_dir'].strip()!r} != {entry['evidence_dir']!r}")


def run_notes_justify_fewer(root: Path) -> bool:
    path = root / "RUN_NOTES.md"
    if not path.is_file():
        return False
    lines, fenced = [], False
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        lines.append((line, fenced or line.lstrip().startswith(("```", "~~~"))))
    for i, (line, in_code) in enumerate(lines):
        heading = None if in_code else re.match(r"^(#{1,6})\s+.*fewer than 15", line, re.IGNORECASE)
        if heading:
            body = []
            for following, following_in_code in lines[i + 1 :]:
                other = None if following_in_code else re.match(r"^(#{1,6})\s", following)
                if other and len(other.group(1)) <= len(heading.group(1)):
                    break
                body.append(following)
            return len("\n".join(body).strip()) >= 200
    return False


def check(root: Path, jobs: int) -> Report:
    rep = Report()
    board = read_json(root / "results" / "leaderboard.json", rep, "leaderboard.json")
    if board is None:
        return rep
    entries = board.get("entries") if isinstance(board, dict) else board
    if not isinstance(entries, list):
        rep.fail("leaderboard.json", 'expected {"entries": [...]} or a list of entries')
        return rep

    valid, seen = [], set()
    for i, entry in enumerate(entries):
        where = entry.get("env_id") if isinstance(entry, dict) and nonempty_str(entry.get("env_id")) else f"entry {i}"
        if where != f"entry {i}" and not ENV_ID.match(where):
            rep.fail(where, "env_id must be a hub id of the form owner/name")
            continue
        key = where.lower().replace("_", "-")
        if key in seen:
            rep.fail(where, "duplicate env_id")
            continue
        seen.add(key)
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
        if entry["status"] == "failed_to_run":
            check_failed_entry(entry, root, rep)

    def evaluate(entry):
        try:
            return evaluate_entry(entry, root, entry["env_id"])
        except Exception as e:  # noqa: BLE001 - a malformed input must be reported, not crash the run
            sub = Report()
            sub.fail(entry["env_id"], f"checker error while evaluating: {type(e).__name__}: {e}")
            return sub

    scored = [e for e in valid if e["status"] != "failed_to_run"]
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        reports = list(pool.map(evaluate, scored))
    loaded = {}
    for entry, sub in zip(scored, reports):
        rep.extend(sub)
        if sub.signature is not None:
            if sub.signature in loaded:
                rep.fail(entry["env_id"], f"loads the same environment as {loaded[sub.signature]} (each environment counts once)")
            loaded.setdefault(sub.signature, entry["env_id"])

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

"""Dump dataset rows and grader source of a hub env. Runs inside the env's own venv:

    <venv>/bin/python -I harden/audit/inspect_env.py JOB.json OUT.json

JOB {"root", "runtime", "indices", "answer_field", "gold", "sources"}
OUT {"dataset_size", "rows": {"<i>": {"digest", "messages", "gold", "info"}}, "sources": {path: text}}

Rows are loaded with the checker's own loader, so digests match what it recomputes.
"""

import asyncio  # noqa: F401  (the checker's helpers expect it importable)
import inspect
import json
import sys
import traceback
from pathlib import Path

MAX_SOURCE_CHARS = 40000


def _message(m):
    if isinstance(m, dict):
        return {"role": m.get("role"), "content": m.get("content")}
    return {"role": getattr(m, "role", None), "content": getattr(m, "content", None)}


def _legacy_rows(ck, env, runtime, job):
    examples, size = ck._legacy_examples(env, runtime, job["indices"])
    rows = {}
    for i, (dig, row) in examples.items():
        prompt = row.get("prompt")
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else [_message(m) for m in prompt or []]
        if job.get("gold") == "rg_dataset":
            gold = env.rg_dataset[int(row["answer"])]["answer"]
        else:
            gold = row.get(job.get("answer_field") or "answer")
        info = row.get("info")
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except ValueError:
                pass
        rows[str(i)] = {"digest": dig, "messages": messages, "gold": None if gold is None else str(gold), "info": info}
    return rows, size


def _v1_rows(ck, taskset, job):
    examples, size = ck._v1_examples(taskset, job["indices"])
    rows = {}
    for i, (dig, task) in examples.items():
        data = task.data
        messages = []
        if data.system_prompt:
            messages.append({"role": "system", "content": data.system_prompt})
        prompt = data.prompt
        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
        else:
            messages.extend(_message(m) for m in prompt or [])
        gold = getattr(data, job.get("answer_field") or "answer", None)
        rows[str(i)] = {"digest": dig, "messages": messages, "gold": None if gold is None else str(gold), "info": {}}
    return rows, size


def _source_files(runtime, obj):
    files = []

    def add(thing):
        try:
            path = inspect.getsourcefile(inspect.unwrap(thing))
        except (TypeError, OSError):
            return
        if path and path not in files:
            files.append(path)

    if runtime["api"] == "legacy":
        module = sys.modules.get(runtime["load_id"].replace("-", "_").split("/")[-1])
        if module is not None:
            add(module)

        def add_parser(parser):
            add(type(parser))
            extract = getattr(parser, "extract_fn", None)
            if callable(extract):
                add(extract)

        def walk(rubric):
            add(type(rubric))
            for func in getattr(rubric, "funcs", None) or getattr(rubric, "reward_funcs", None) or []:
                add(func)
            for sub in getattr(rubric, "rubrics", None) or []:
                walk(sub)
            parser = getattr(rubric, "parser", None)
            if parser is not None:
                add_parser(parser)

        walk(obj.rubric)
        if getattr(obj, "parser", None) is not None:
            add_parser(obj.parser)
    else:
        add(type(obj))
        add(obj.task_type())
        from verifiers.v1.utils import score

        add(score)
    keep = [
        f for f in files
        if not f.endswith("/multiturn_env.py")
        and ("/verifiers/" not in f or not f.endswith(("/rubric.py", "/rubric_group.py", "/monitor_rubric.py")))
    ]
    out = {}
    for path in keep:
        text = Path(path).read_text(errors="replace")
        if len(text) > MAX_SOURCE_CHARS:
            text = text[:MAX_SOURCE_CHARS] + "\n# ... truncated ...\n"
        short = path.split("site-packages/")[-1]
        out[short] = text
    return out


def _task_scorers(rows):
    """reasoning-core dispatches to one scorer per task type: the scorers of these rows."""
    try:
        from reasoning_core import registry
    except ImportError:
        return {}
    out = {}
    for row in rows.values():
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        metadata = info.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                metadata = {}
        name = (metadata or {}).get("_task") or info.get("task_name")
        if not name:
            continue
        try:
            name = registry.match_task_name(name, include_dev=True)
            if name in registry.COLLECTIONS:
                fn = registry.get_task(name).score_answer
            else:
                fn = (registry.DATASETS if name in registry.DATASETS else registry.DEV_DATASETS)[name].score_answer
            fn = inspect.unwrap(fn)
            path = inspect.getsourcefile(fn).split("site-packages/")[-1]
            out[f"{path} :: score_answer used for task '{name}'"] = inspect.getsource(fn)
        except Exception as e:  # noqa: BLE001 - a missing scorer only shortens the context
            out[f"scorer for task '{name}'"] = f"# source unavailable: {type(e).__name__}: {e}"
    return out


def main(job_path, out_path):
    job = json.loads(Path(job_path).read_text())
    out = {"fatal": None}
    try:
        root = Path(job["root"])
        sys.path.insert(0, str(root / "scripts"))
        import check_leaderboard as ck

        runtime = {**job["runtime"], "env_args": job["runtime"].get("env_args") or {}}
        obj = ck._load(runtime, "original", root)
        if runtime["api"] == "legacy":
            out["rows"], out["dataset_size"] = _legacy_rows(ck, obj, runtime, job)
        else:
            out["rows"], out["dataset_size"] = _v1_rows(ck, obj, job)
        if job.get("sources"):
            out["sources"] = _source_files(runtime, obj)
            out["sources"].update(_task_scorers(out["rows"]))
    except BaseException as e:  # noqa: BLE001
        out["fatal"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()[-4000:]
    Path(out_path).write_text(json.dumps(out, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

"""The full loop for one game: compile -> harden -> train (hardened and hacked) -> replay page.

    python scripts/pipeline.py "Bulls and cows with 3 distinct digits ..." --gpus 0,1
    python scripts/pipeline.py --game number_hunt_easy --gpus 0,1        # skip compiling
    python scripts/pipeline.py --game compiled/game_ab12cd34.py --steps 30

1. compile (env_compiler, Claude Haiku): the fit check routes the description to a single- or
   multi-turn game, or refuses it.
2. harden (harden.game_audit): the hacker probes the shipped game, the exact rules verify, the
   fixer writes `tighten`; output hardened/<name>.py.
3. train: hardened run on hardened/<name>.py with the original game as the held-out oracle,
   and the hacked run on the shipped game's loose reward, in parallel on two GPUs (one GPU:
   one after the other). Single-turn runs use vLLM.
4. trainer.rollout + trainer.viz: base, hardened and hacked policies replayed on the same
   held-out tasks, written to demo/loophole_replay.html.

The environment's status in invariants.db follows the stages (compiling, hardening, training,
done) for the dashboard. Run from the repo root inside the trainer venv.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env_compiler import compile as comp  # noqa: E402
from env_compiler.loader import load_game  # noqa: E402
from harden.game_audit import GameAudit  # noqa: E402
from harden.store import mirror  # noqa: E402


def run(cmd: list[str], log: Path, gpu: str | None = None) -> subprocess.Popen:
    env = dict(os.environ, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    if gpu is not None:
        env["CUDA_VISIBLE_DEVICES"] = gpu
    print(f"$ {' '.join(cmd)}  > {log.relative_to(ROOT)}" + (f"  (GPU {gpu})" if gpu else ""))
    return subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT)


def wait(procs: list[tuple[str, subprocess.Popen]]) -> None:
    failed = [name for name, p in procs if p.wait() != 0]
    if failed:
        raise SystemExit(f"failed: {', '.join(failed)} (see runs/*.log)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("description", nargs="?", help="plain-English game description to compile")
    p.add_argument("--game", help="skip compiling: a built-in game name or a game module path")
    p.add_argument("--gpus", default="0,1", help="one or two GPU ids")
    p.add_argument("--steps", type=int, default=60)
    p.add_argument("--lr", type=float, help="default: 2e-5 single-turn, 5e-6 multi-turn")
    p.add_argument("--shots", type=int, default=0, help="single-turn prompt shots")
    p.add_argument("--cap", type=float, default=None, help="optional hardening spend cap in USD; disabled by default")
    p.add_argument("--single-only", action="store_true", help="refuse games the fit check calls multi-turn")
    args = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # progress shows up live when logged to a file
    if not (args.description or args.game):
        p.error("give a description or --game")
    py = sys.executable

    from harden.store.moss_retrieval import require_moss_config
    require_moss_config()  # retrieval must be configured before paid compilation

    # 1. compile
    ref = args.game
    if ref is None:
        comp.load_dotenv()
        result = comp.compile_game(args.description, ROOT / "compiled", allow_multiturn=not args.single_only)
        if not result.ok:
            print(f"compile refused or failed: {result.reason}")
            if result.suggestions:
                print("Try one of:\n  - " + "\n  - ".join(result.suggestions))
            return 1
        ref = str(result.path.relative_to(ROOT))
        print(f"compiled {ref} after {result.attempts} attempt(s)")
    game = load_game(ref, strict=False)
    kind, name = getattr(game, "kind", "single"), game.name
    print(f"game {name} ({kind}-turn)")

    # 2. harden
    audit = GameAudit(ref, args.cap, None)
    report = audit.run()
    hardened = report["hardened_module"] or ref  # robust: the shipped game had nothing to patch
    mirror.record_environment(audit.env_id, source="game", title=name, status="training")

    # 3. train
    lr = args.lr or (5e-6 if kind == "multi" else 2e-5)
    common = ["--steps", str(args.steps), "--lr", str(lr)]
    if kind == "single":
        common += ["--vllm", "--shots", str(args.shots)]
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    jobs = [
        ("hardened", [py, "-m", "trainer.train", hardened, "--oracle", ref, "--out", f"runs/{name}-hardened", *common]),
        ("hacked", [py, "-m", "trainer.train", ref, "--loose", "--out", f"runs/{name}-hacked", *common]),
    ]
    gpus = args.gpus.split(",")
    if len(gpus) >= 2:
        wait([(label, run(cmd, runs / f"{name}-{label}.log", gpus[i])) for i, (label, cmd) in enumerate(jobs)])
    else:
        for label, cmd in jobs:
            wait([(label, run(cmd, runs / f"{name}-{label}.log", gpus[0]))])

    # 4. replay page
    wait([("rollout", run([py, "-m", "trainer.rollout", ref, "--runs", name], runs / f"{name}-rollout.log", gpus[0]))])
    wait([("viz", run([py, "-m", "trainer.viz"], runs / f"{name}-viz.log"))])
    mirror.record_environment(audit.env_id, source="game", title=name, status="done")
    print(f"done: {name}. Curves in runs/{name}-{{hardened,hacked}}/metrics.jsonl, page demo/loophole_replay.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())

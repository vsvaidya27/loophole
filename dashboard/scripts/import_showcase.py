"""Import recorded showcase assets from a Git ref without merging its application code.

Run from the repository root: python3 dashboard/scripts/import_showcase.py --ref upstream/showcase
Audio is extracted into lazy-loaded files; the recorded scores and provenance are preserved.
"""
import argparse
import base64
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
ORDER = ["snake", "trading", "webagent", "voice"]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="upstream/showcase")
    args = parser.parse_args()
    revision = git("rev-parse", "--verify", args.ref).decode().strip()
    read = lambda path: git("show", f"{revision}:{path}")
    public = DASHBOARD / "public" / "showcase"
    catalog = []
    for name in ORDER:
        card = json.loads(read(f"showcase/{name}/card.json"))
        filename = "voice.json" if name == "voice" else "rollouts.json"
        source = f"showcase/{name}/artifacts/{filename}"
        data = json.loads(read(source))
        for call_index, call in enumerate(data.get("calls", [])):
            for turn, audio in enumerate(call.get("audio", [])):
                if audio and audio.startswith("data:audio/mpeg;base64,"):
                    audio_path = f"audio/voice-{call_index}-{turn}.mp3"
                    target = public / audio_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(base64.b64decode(audio.split(",", 1)[1], validate=True))
                    call["audio"][turn] = f"/showcase/{audio_path}"
        for folder in ["data", "videos"]:
            (public / folder).mkdir(parents=True, exist_ok=True)
        (public / "data" / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")))
        (public / "videos" / f"{name}.mp4").write_bytes(read(f"dashboard/public/videos/{name}.mp4"))
        scores = {}
        for policy in data.get("policies", []):
            rows = [task["rollouts"][policy] for task in data["tasks"] if policy in task["rollouts"]]
            scores[policy] = {key: sum(row[key] for row in rows) / len(rows) for key in ["strict", "loose"]}
        catalog.append({
            **{key: card[key] for key in ["id", "title", "game", "hook", "loophole"]},
            "placeholder": data["placeholder"], "kind": data.get("kind", "single"),
            "samples": len(data.get("tasks", data.get("calls", []))), "scores": scores,
            "summary": data.get("summary"), "description": data["description"],
            "source": source, "video": f"/showcase/videos/{name}.mp4", "data": f"/showcase/data/{name}.json",
        })
    target = DASHBOARD / "src" / "showcase" / "catalog.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"revision": revision, "demos": catalog}, indent=2) + "\n")
    print(f"Imported {len(catalog)} demos from {revision[:7]}; recorded scores and placeholder labels preserved.")


if __name__ == "__main__":
    main()

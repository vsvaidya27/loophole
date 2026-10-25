"""Build the voice tab: recorded refund-desk calls scored by the baseline and the hardened judge.

    python -m showcase.voice.build_voice --rejudge          # re-score the picked calls with both judge prompts
    python -m showcase.voice.build_voice --rejudge --audio  # also speak the lines with Cartesia voices

Input is an audit run from `python -m voice_env.harden` (default results/voice_audit_llm). The calls
and ground truth are the audit's own; --rejudge asks the judge model (Haiku) for a verdict on each
picked call under BOTH prompts so the page can show them side by side. The audit only stored the
final judge's verdict, so --rejudge is needed to build the file; the result is committed.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from ..cards import ROOT

SRC = Path("results/voice_audit_llm")
OUT = ROOT / "voice" / "artifacts" / "voice.json"
AGENT_VOICE = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"  # Skylar
CUSTOMER_VOICE = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # Daniel


def parse_transcript(text: str) -> list[list[str]]:
    """'Agent: hi\\nCustomer: hello' -> [["Agent", "hi"], ["Customer", "hello"]] (continuation lines join up)."""
    turns: list[list[str]] = []
    for line in text.splitlines():
        who, sep, rest = line.partition(": ")
        if sep and who in ("Agent", "Customer"):
            turns.append([who, rest])
        elif turns and line.strip():
            turns[-1][1] += " " + line.strip()
    return turns


def pick_calls(attacks: list[dict], benign: list[dict], verdicts: dict[str, dict] | None = None, n_flawed: int = 3, n_honest: int = 2):
    """Flawed calls first where the baseline judge was fooled, then honest calls both judges pass."""
    def fooled(r):  # baseline said success on a call that really went wrong
        v = (verdicts or {}).get(key(r), {}).get("baseline")
        return bool(v and v["success"] and not r["true_success"])

    wrong = [r for r in attacks if not r["true_success"]]
    wrong.sort(key=lambda r: (not fooled(r), r["decision"] != "refund", r["case_id"]))
    seen_cases, flawed = set(), []
    for r in wrong:  # one call per customer persona and decision, for variety
        k = (r["persona"], r["decision"])
        if k not in seen_cases:
            seen_cases.add(k)
            flawed.append(r)
    honest = [r for r in benign if r["true_success"]]
    return flawed[:n_flawed], honest[:n_honest]


def label_for(record: dict, honest: bool) -> str:
    if honest:
        return f"Honest agent: {record['decision']} (what the policy requires)"
    verb = {"refund": "approved a refund", "deny": "denied the request", "escalate": "escalated to another team", "none": "never reached a decision"}
    return f"Flawed agent: {verb.get(record['decision'], record['decision'])}, policy says {record['correct_action']}"


def key(record: dict) -> str:
    return f"{record['kind']}:{record['case_id']}:{record['strategy'][:30]}"


def rejudge(records: list[dict], prompts: dict[str, str]) -> dict[str, dict]:
    from voice_env.judge import judge
    from voice_env.llm import sim_llm

    llm = sim_llm()
    out = {}
    for r in records:
        out[key(r)] = {}
        for name, prompt in prompts.items():
            ok, reason = judge(llm, prompt, r["transcript"])
            out[key(r)][name] = {"success": ok, "reason": reason}
    return out


def speak(turns: list[list[str]]) -> list[str]:
    import httpx

    from voice_env.cartesia import BASE, VERSION, Cartesia

    cartesia = Cartesia()
    clips = []
    for who, text in turns:
        voice = AGENT_VOICE if who == "Agent" else CUSTOMER_VOICE
        r = httpx.post(
            f"{BASE}/tts/bytes",
            headers={"X-API-Key": cartesia.key, "Cartesia-Version": VERSION},
            json={"model_id": "sonic-3", "transcript": text, "voice": {"id": voice}, "language": "en",
                  "output_format": {"container": "mp3", "sample_rate": 24000, "bit_rate": 64000}},
            timeout=90,
        )
        r.raise_for_status()
        clips.append("data:audio/mpeg;base64," + base64.b64encode(r.content).decode())
    return clips


def build(src: Path, do_rejudge: bool, do_audio: bool, out: Path) -> dict:
    read = lambda name: [json.loads(line) for line in (src / name).read_text().splitlines() if line.strip()]  # noqa: E731
    attacks, benign = read("attempts.jsonl"), read("benign.jsonl")
    summary = json.loads((src / "summary.json").read_text())
    baseline, hardened = (src / "judge_round_1.txt").read_text(), (src / "judge_final.txt").read_text()

    verdicts: dict[str, dict] = {}
    if do_rejudge:
        pool = [r for r in attacks if not r["true_success"]] + [r for r in benign if r["true_success"]][:4]
        verdicts = rejudge(pool, {"baseline": baseline, "hardened": hardened})
    flawed, honest = pick_calls(attacks, benign, verdicts)

    calls = []
    for honest_flag, group in ((False, flawed), (True, honest)):
        for r in group:
            v = verdicts.get(key(r)) or {"hardened": {"success": r["judge_success"], "reason": r["reason"]}}
            if "baseline" not in v:  # no side-by-side without --rejudge
                continue
            turns = parse_transcript(r["transcript"])
            calls.append({
                "id": key(r),
                "label": label_for(r, honest_flag),
                "honest": honest_flag,
                "correct_action": r["correct_action"],
                "decision": r["decision"],
                "true_success": r["true_success"],
                "transcript": turns,
                "verdicts": {"baseline": v["baseline"], "hardened": v["hardened"]},
                "audio": speak(turns) if do_audio else None,
            })
    data = {
        "game": "voice_refund_desk",
        "kind": "voice",
        "description": "A phone support agent for an electronics store follows a refund policy. An LLM judge scores each call, "
                       "and that judge is the reward we are hardening.",
        "loophole": "The baseline judge asks whether the agent gave a clear outcome, so a confident wrong refund passes.",
        "provenance": f"Calls and ground truth come from the audit in {src}; verdicts are re-scored by the judge model under both prompts. "
                      "Voices are Cartesia Sonic reading the transcript." if do_audio else
                      f"Calls and ground truth come from the audit in {src}; verdicts are re-scored by the judge model under both prompts.",
        "placeholder": False,
        "summary": {k: summary[k] for k in ("asr_before", "asr_after", "benign_pass_before", "benign_pass_after")}
                   | {"benign_before": summary["benign_pass_before"], "benign_after": summary["benign_pass_after"]},
        "judges": {"baseline": baseline, "hardened": hardened},
        "calls": calls,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data))
    print(f"wrote {out}: {len(calls)} calls, audio={'yes' if do_audio else 'no'}")
    return data


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--src", type=Path, default=SRC)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--rejudge", action="store_true")
    p.add_argument("--audio", action="store_true")
    args = p.parse_args()
    build(args.src, args.rejudge, args.audio, args.out)


if __name__ == "__main__":
    main()

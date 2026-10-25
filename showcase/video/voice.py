"""The voice demo as a video with a real audio track.

Recorded refund-desk calls play out line by line in Cartesia voices (agent Skylar, customer Daniel)
with a level meter driven by the audio. When each call ends, the baseline judge and the hardened
judge reveal their verdicts against the ground truth, and a banner flags a fooled judge.
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import wave
from pathlib import Path

from . import canvas as cv
from .canvas import C, badge, font, panel, rrect, text, wrap

SR = 24000
SPF = SR // cv.FPS  # audio samples per video frame
AGENT, CUSTOMER = C["hard"], (176, 132, 233)


def decode_mp3(data_uri: str) -> bytes:
    raw = base64.b64decode(data_uri.split(",", 1)[1])
    out = subprocess.run(
        [cv.ffmpeg_bin(), "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ar", str(SR), "-ac", "1", "pipe:1"],
        input=raw, stdout=subprocess.PIPE, check=True).stdout
    return out + b"\0\0" * ((-len(out) // 2) % SPF)  # pad to a whole number of video frames


def levels(pcm: bytes) -> list[float]:
    """Loudness per video frame, scaled so the loudest frame is 1."""
    import array

    samples = array.array("h")
    samples.frombytes(pcm)
    out = []
    for i in range(0, len(samples), SPF):
        chunk = samples[i : i + SPF]
        out.append((sum(x * x for x in chunk) / max(1, len(chunk))) ** 0.5)
    peak = max(out) or 1
    return [v / peak for v in out]


class Track:
    """Frames and audio are appended together so they stay aligned."""

    def __init__(self, writer: cv.Writer):
        self.w, self.audio = writer, bytearray()

    def silent(self, img, seconds: float):
        n = max(1, round(seconds * cv.FPS))
        self.w.add(img, n / cv.FPS)
        self.audio += b"\0\0" * SPF * n

    def clip(self, frame_for, pcm: bytes):
        lv = levels(pcm)
        for i, level in enumerate(lv):
            self.w.add(frame_for(level, i / cv.FPS), 1 / cv.FPS)
        self.audio += pcm


class Scene:
    def __init__(self, data: dict, card: dict):
        self.data, self.card = data, card

    def header(self, d):
        text(d, (28, 22), self.card["title"], font(32, bold=True), C["fg"])
        text(d, (28, 64), wrap(d, self.card["hook"], font(17), 960, 1)[0], font(17), C["fg2"])
        badge(d, (cv.W - 28 - 205, 26), "RECORDED CALLS", C["good"])

    def avatar(self, d, cx, cy, name, sub, color, active, level):
        if active:
            d.ellipse((cx - 44, cy - 44, cx + 44, cy + 44), outline=color, width=4)
        d.ellipse((cx - 36, cy - 36, cx + 36, cy + 36), fill=C["surface2"])
        text(d, (cx, cy), name[0], font(34, bold=True), color, "mm")
        text(d, (cx, cy + 60), name, font(18, bold=True), C["fg"], "mm")
        text(d, (cx, cy + 82), sub, font(13), C["fg3"], "mm")
        for k in range(9):  # level bars beside the avatar
            h = 6 + (level * 34 * (0.5 + 0.5 * ((k * 5 + 3) % 7) / 6)) if active else 4
            x = cx + 58 + k * 9
            d.rounded_rectangle((x, cy - h / 2, x + 5, cy + h / 2), radius=2, fill=color if active else C["line"])

    def verdict_box(self, d, box, label, color, state, v=None):
        x0, y0, x1, y1 = box
        rrect(d, box, fill=C["surface"], outline=C["line"], r=10)
        d.rectangle((x0, y0 + 10, x0 + 5, y1 - 10), fill=color)
        text(d, (x0 + 18, y0 + 14), label.upper(), font(13, mono=True, bold=True), C["fg3"])
        if state == "wait":
            text(d, (x0 + 18, y0 + 44), "waiting for the call to end", font(15), C["fg3"])
        elif state == "judging":
            text(d, (x0 + 18, y0 + 44), "reading the transcript…", font(16), C["fg2"])
        else:
            ok = v["success"]
            text(d, (x0 + 18, y0 + 38), "PASS · call judged a success" if ok else "FAIL · call judged a failure",
                 font(17, mono=True, bold=True), C["good"] if ok else C["crit"])
            for k, ln in enumerate(wrap(d, v["reason"], font(14), x1 - x0 - 36, 3)):
                text(d, (x0 + 18, y0 + 66 + k * 18), ln, font(14), C["fg2"])

    def frame(self, call: dict, n_lines: int, level: float, stage: int, cap: str, flash=False):
        """stage: 0 call in progress, 1 judging, 2 baseline shown, 3 both shown."""
        img, d = cv.new_frame()
        self.header(d)
        who = call["transcript"][n_lines - 1][0] if n_lines else None
        panel(d, (28, 100, 760, 620), C["hard"])
        self.avatar(d, 150, 190, "Agent", "support agent · Skylar", AGENT, who == "Agent" and stage == 0, level)
        self.avatar(d, 470, 190, "Customer", "simulated customer · Daniel", CUSTOMER, who == "Customer" and stage == 0, level)
        shown = call["transcript"][max(0, n_lines - 3): n_lines]
        y = 330
        for k, (name, line) in enumerate(shown):
            last = k == len(shown) - 1
            col = AGENT if name == "Agent" else CUSTOMER
            lines = wrap(d, line, font(19), 690, 4 if last else 2)
            text(d, (52, y), name.upper(), font(12, mono=True, bold=True), col if last else C["fg3"])
            y += 18
            for ln in lines:
                text(d, (52, y), ln, font(19), C["fg"] if last else C["fg3"])
                y += 25
            y += 10
        # right column: ground truth and the two judges
        gx0, gx1 = 784, cv.W - 28
        ended = stage >= 1
        rrect(d, (gx0, 100, gx1, 206), fill=C["surface"], outline=C["line"], r=10)
        text(d, (gx0 + 18, 114), "GROUND TRUTH", font(13, mono=True, bold=True), C["fg3"])
        text(d, (gx0 + 18, 138), f"Policy says: {call['correct_action']}", font(18, bold=True), C["fg"])
        if ended:
            right = call["decision"] == call["correct_action"]
            text(d, (gx0 + 18, 168), f"Agent did: {call['decision']}  ·  {'correct' if right else 'WRONG'}", font(18, bold=True), C["good"] if right else C["crit"])
        else:
            text(d, (gx0 + 18, 168), "Agent did: …", font(18), C["fg3"])
        states = [("wait", "wait"), ("judging", "judging"), ("show", "judging"), ("show", "show")][stage]
        self.verdict_box(d, (gx0, 218, gx1, 358), "Baseline judge", C["hack"], states[0], call["verdicts"]["baseline"])
        self.verdict_box(d, (gx0, 370, gx1, 510), "Hardened judge", C["hard"], states[1], call["verdicts"]["hardened"])
        fooled = stage >= 2 and call["verdicts"]["baseline"]["success"] and not call["true_success"]
        if fooled:
            rrect(d, (gx0, 524, gx1, 560), fill=C["warnbg"], outline=C["warn"] if flash else C["crit"], r=8, width=2)
            text(d, ((gx0 + gx1) / 2, 542), "JUDGE FOOLED · passed a wrong call", font(17, bold=True), C["warn"] if flash else C["fg"], "mm")
        elif stage >= 2 and not call["verdicts"]["baseline"]["success"] and call["true_success"]:
            rrect(d, (gx0, 524, gx1, 560), fill=C["warnbg"], outline=C["crit"], r=8, width=2)
            text(d, ((gx0 + gx1) / 2, 542), "JUDGE WRONG · failed a correct call", font(17, bold=True), C["fg"], "mm")
        rrect(d, (28, 634, cv.W - 28, 704), fill=C["surface2"], r=12)
        lines = wrap(d, cap, font(22), cv.W - 100, 2)
        yy = 669 - 14 * len(lines) + 2
        for ln in lines:
            text(d, (46, yy), ln, font(22), C["fg"])
            yy += 30
        return img

    def intro(self):
        img, d = cv.new_frame()
        text(d, (cv.W / 2, 200), self.card["title"], font(60, bold=True), C["fg"], "mm")
        for k, ln in enumerate(wrap(d, self.card["hook"], font(28), 1000, 3)):
            text(d, (cv.W / 2, 290 + k * 40), ln, font(28), C["fg2"], "mm")
        for k, ln in enumerate(wrap(d, "The reward here is an LLM judge that scores each call. We compare the first judge with the one our hacker and fixer produced.", font(22), 980, 3)):
            text(d, (cv.W / 2, 450 + k * 32), ln, font(22), C["warn"], "mm")
        return img

    def outro(self):
        img, d = cv.new_frame()
        s = self.data["summary"]
        text(d, (cv.W / 2, 120), "Same calls, two judges", font(44, bold=True), C["fg"], "mm")
        for i, (name, color, asr, ben) in enumerate([("Baseline judge", C["hack"], s["asr_before"], s["benign_before"]),
                                                       ("Hardened judge", C["hard"], s["asr_after"], s["benign_after"])]):
            x0 = 120 + i * 560
            panel(d, (x0, 200, x0 + 480, 560), color)
            text(d, (x0 + 24, 232), name, font(26, bold=True), C["fg"])
            text(d, (x0 + 24, 290), f"{round(asr * 100)}%", font(96, bold=True), C["fg"])
            text(d, (x0 + 24, 400), "OF WRONG CALLS PASSED", font(14, mono=True, bold=True), C["fg3"])
            text(d, (x0 + 24, 450), f"{round(ben * 100)}%", font(56, bold=True), C["good"] if ben >= 0.9 else C["crit"])
            text(d, (x0 + 24, 520), "OF HONEST CALLS PASSED", font(14, mono=True, bold=True), C["fg3"])
        rrect(d, (28, 634, cv.W - 28, 704), fill=C["surface2"], r=12)
        text(d, (46, 669), self.card["expected"], font(22), C["fg"], "lm")
        return img


def clip_seconds(call: dict) -> float:
    """Audio length from the mp3 sizes (the clips are 64 kbit/s, about 8000 bytes a second)."""
    return sum(len(c.split(",", 1)[1]) * 3 / 4 for c in call["audio"]) / 8000


def pick_for_video(calls: list[dict], budget_s: float = 90.0) -> list[dict]:
    """The most telling calls that fit the budget: a fooled baseline judge first, then an honest call
    the baseline got wrong, then more fooled calls, then the rest."""
    def fooled(c):
        return c["verdicts"]["baseline"]["success"] and not c["true_success"]

    def wronged(c):
        return c["honest"] and not c["verdicts"]["baseline"]["success"]

    first_fooled = [c for c in calls if fooled(c) and c["decision"] == "refund"][:1]
    ordered = first_fooled + [c for c in calls if wronged(c)][:1] + [c for c in calls if fooled(c)] + calls
    picked, used = [], 0.0
    for c in ordered:
        if c in picked or used + clip_seconds(c) > budget_s and picked:
            continue
        picked.append(c)
        used += clip_seconds(c)
    return picked


def render_voice(card: dict, stills: Path | None = None, out: Path | None = None, budget_s: float = 90.0) -> Path:
    from ..cards import ROOT

    data = json.loads((ROOT / "voice" / "artifacts" / "voice.json").read_text())
    calls = pick_for_video([c for c in data["calls"] if c.get("audio")], budget_s)
    if not calls:
        raise SystemExit("voice.json has no audio; rebuild it with showcase.voice.build_voice --audio")
    scene = Scene(data, card)
    out = out or ROOT / "voice" / "video" / "voice.mp4"
    silent = out.with_suffix(".silent.mp4")
    with cv.Writer(silent) as w:
        track = Track(w)
        track.silent(scene.intro(), 4.0)
        for n, call in enumerate(calls, 1):
            kind = "honest agent" if call["honest"] else "flawed agent"
            head = f"Call {n} of {len(calls)}: {call['label']}"
            track.silent(scene.frame(call, 0, 0, 0, head), 2.0)
            for i, clip in enumerate(call["audio"], 1):
                pcm = decode_mp3(clip)
                track.clip(lambda lv, t, i=i: scene.frame(call, i, lv, 0, head), pcm)
                track.silent(scene.frame(call, i, 0, 0, head), 0.25)
            last = len(call["transcript"])
            track.silent(scene.frame(call, last, 0, 1, "The call is over. Both judges read the transcript."), 1.4)
            wrong = not call["true_success"]
            track.silent(scene.frame(call, last, 0, 2, "The baseline judge asks whether the agent gave a clear outcome."), 2.0)
            msg = ("The baseline judge passed a call the policy says was wrong. A confident wrong refund looks like success."
                   if call["verdicts"]["baseline"]["success"] and wrong else
                   "The baseline judge failed a correct call: the customer was unhappy, so it assumed the agent erred."
                   if (not call["verdicts"]["baseline"]["success"]) and call["true_success"] else "The baseline judge agrees with the ground truth.")
            for j in range(6):
                track.silent(scene.frame(call, last, 0, 3, msg, flash=j % 2 == 0), 0.4)
            track.silent(scene.frame(call, last, 0, 3, "The hardened judge checks the decision against the policy, so it gets this call right."), 2.4)
            if stills and n == 1:
                stills.mkdir(parents=True, exist_ok=True)
                scene.frame(call, last, 0, 3, msg, True).save(stills / "voice_verdicts.png")
                scene.frame(call, 2, 0.8, 0, head).save(stills / "voice_call.png")
        track.silent(scene.outro(), 5.0)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        with wave.open(str(wav), "wb") as f:
            f.setnchannels(1), f.setsampwidth(2), f.setframerate(SR)
            f.writeframes(bytes(track.audio))
        cv.mux_audio(silent, wav, out)
    silent.unlink()
    return out

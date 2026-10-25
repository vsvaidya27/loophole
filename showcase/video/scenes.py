"""The comparison video: base, hacked and fixed policies play the same tasks side by side,
a meter shows the true score against what the hackable reward pays, and a banner flags the hack."""

from __future__ import annotations

from pathlib import Path

from . import canvas as cv
from .canvas import C, POLICY_COLOR, badge, font, meter, panel, rrect, text, wrap
from .painters import Painter

PAD, COLW, GAP = 28, 392, 24
PY0, PY1 = 100, 620
POLICIES = [("base", "Base model", "before any training"), ("hacked", "Trained on hackable env", "rewarded for the loophole"),
            ("hardened", "Trained on fixed env", "rewarded for the real task")]
STEP_S = 0.55


def colx(i: int) -> tuple[int, int]:
    x0 = PAD + i * (COLW + GAP)
    return x0, x0 + COLW


def select_tasks(data: dict, k: int) -> list[int]:
    """Prefer tasks where the hacked policy is paid for a wrong answer and the fixed policy wins
    (and the base model fails), the same order the page uses."""
    from ..build import contrast_rank

    return sorted(range(len(data["tasks"])), key=lambda i: (*contrast_rank(data["tasks"][i]), i))[:k]


def header(d, card: dict, tag: str | None):
    text(d, (PAD, 22), card["title"], font(32, bold=True), C["fg"])
    sub = wrap(d, card["hook"], font(17), 960, 1)[0]
    text(d, (PAD, 64), sub, font(17), C["fg2"])
    if tag:
        badge(d, (cv.W - PAD - d.textlength(tag, font=font(15, mono=True, bold=True)) - 20, 26), tag, C["warn"])


def caption(d, s: str, tone=None):
    rrect(d, (PAD, 634, cv.W - PAD, 704), fill=C["surface2"], r=12)
    lines = wrap(d, s, font(22), cv.W - 2 * PAD - 36, 2)
    y = 669 - 14 * len(lines) + 2
    for ln in lines:
        text(d, (PAD + 18, y), ln, font(22), tone or C["fg"])
        y += 30


def pct(v: float) -> str:
    return f"{round(v * 100)}%"


class Compare:
    def __init__(self, data: dict, card: dict, painter: Painter, tag: str | None):
        self.data, self.card, self.painter, self.tag = data, card, painter, tag

    # ---- one frame --------------------------------------------------------------
    def frame(self, ti: int, step: int, show: float, flash: bool, cap: str, cap_tone=None):
        img, d = cv.new_frame()
        header(d, self.card, self.tag)
        task = self.data["tasks"][ti]
        for i, (key, name, sub) in enumerate(POLICIES):
            row = task["rollouts"].get(key)
            if not row:
                continue
            x0, x1 = colx(i)
            color = POLICY_COLOR[key]
            panel(d, (x0, PY0, x1, PY1), color)
            text(d, (x0 + 18, PY0 + 22), name, font(20, bold=True), C["fg"])
            text(d, (x0 + 18, PY0 + 47), sub + (" · scripted" if self.tag and "PLACEHOLDER" in self.tag else ""), font(14), C["fg3"])
            n = self.painter.steps(task, row)
            s = min(step, n)
            self.painter.draw(d, (x0 + 16, PY0 + 70, x1 - 16, PY0 + 318), task, row, s)
            if key == "hacked" and show >= 1 and row["loose"] - row["strict"] > 0.01:
                self.hack_banner(d, (x0 + 16, PY0 + 324, x1 - 16, PY0 + 352), row, flash)
            reply = self.painter.reply(task, row)
            ry = PY0 + 358
            text(d, (x0 + 18, ry), "REPLY", font(12, mono=True, bold=True), C["fg3"])
            for k, ln in enumerate(wrap(d, reply.replace("\n", " "), font(14, mono=True), COLW - 36, 2)):
                text(d, (x0 + 18, ry + 16 + k * 18), ln, font(14, mono=True), C["fg2"])
            st, kind = self.painter.status(task, row, s)
            done = step >= n
            col = C["good"] if (kind == "ok" and done) else C["crit"] if (kind == "bad" and done) else C["fg2"]
            text(d, (x0 + 18, PY0 + 414), st, font(16, mono=True, bold=True), col)
            if show > 0:
                meter(d, (x0 + 18, PY0 + 438, x1 - 18, PY0 + 472), "True score", row["strict"], color, show)
                meter(d, (x0 + 18, PY0 + 474, x1 - 18, PY0 + 508), "Hackable env pays", row["loose"], C["hack"], show)
        caption(d, cap, cap_tone)
        return img

    def hack_banner(self, d, box, row, flash):
        rrect(d, box, fill=C["warnbg"], outline=C["warn"] if flash else C["crit"], r=8, width=2)
        x0, y0, x1, y1 = box
        text(d, ((x0 + x1) / 2, (y0 + y1) / 2), f"REWARD HACKED · pays {pct(row['loose'])}, true {pct(row['strict'])}",
             font(16, bold=True), C["warn"] if flash else C["fg"], "mm")

    # ---- cards ------------------------------------------------------------------
    def title_card(self):
        img, d = cv.new_frame()
        text(d, (cv.W / 2, 190), self.card["title"], font(64, bold=True), C["fg"], "mm")
        for k, ln in enumerate(wrap(d, self.card["hook"], font(28), 1000, 3)):
            text(d, (cv.W / 2, 280 + k * 40), ln, font(28), C["fg2"], "mm")
        y = 420
        widths = [d.textlength(n, font=font(20)) + 34 for _, n, _ in POLICIES]
        x = (cv.W - (sum(widths) + 40 * (len(widths) - 1))) / 2
        for (key, name, sub), w in zip(POLICIES, widths):
            d.ellipse((x, y - 8, x + 16, y + 8), fill=POLICY_COLOR[key])
            text(d, (x + 28, y), name, font(20), C["fg"], "lm")
            x += w + 40
        loophole = "Loophole: " + self.card["loophole"]
        for k, ln in enumerate(wrap(d, loophole, font(22), 1000, 3)):
            text(d, (cv.W / 2, 520 + k * 32), ln, font(22), C["warn"], "mm")
        if self.tag:
            badge(d, (cv.W / 2 - 150, 640), self.tag + " · not trained models", C["warn"])
        return img

    def outro_card(self, show: float):
        img, d = cv.new_frame()
        header(d, self.card, self.tag)
        n = len(self.data["tasks"])
        for i, (key, name, sub) in enumerate(POLICIES):
            rows = [t["rollouts"][key] for t in self.data["tasks"] if key in t["rollouts"]]
            if not rows:
                continue
            x0, x1 = colx(i)
            color = POLICY_COLOR[key]
            panel(d, (x0, PY0, x1, PY1), color)
            text(d, (x0 + 18, PY0 + 22), name, font(20, bold=True), C["fg"])
            text(d, (x0 + 18, PY0 + 47), sub, font(14), C["fg3"])
            strict = sum(r["strict"] for r in rows) / len(rows)
            loose = sum(r["loose"] for r in rows) / len(rows)
            text(d, (x0 + 18, PY0 + 110), pct(strict * show), font(92, bold=True), C["fg"])
            text(d, (x0 + 18, PY0 + 214), f"TRUE SCORE ON {len(rows)} HELD-OUT TASKS", font(13, mono=True, bold=True), C["fg3"])
            meter(d, (x0 + 18, PY0 + 270, x1 - 18, PY0 + 310), "True score", strict, color, show)
            meter(d, (x0 + 18, PY0 + 330, x1 - 18, PY0 + 370), "Hackable env pays", loose, C["hack"], show)
            if key == "hacked" and loose - strict > 0.01 and show >= 1:
                self.hack_banner(d, (x0 + 18, PY0 + 400, x1 - 18, PY0 + 432), {"loose": loose, "strict": strict}, True)
        caption(d, self.card["expected"])
        return img

    # ---- the whole video ----------------------------------------------------------
    def render(self, path: Path, k: int = 3) -> Path:
        picks = select_tasks(self.data, k)
        with cv.Writer(path) as w:
            w.add(self.title_card(), 4.0)
            for n_task, ti in enumerate(picks, 1):
                task = self.data["tasks"][ti]
                rows = task["rollouts"]
                longest = max(self.painter.steps(task, r) for r in rows.values())
                w.add(self.frame(ti, 0, 0, False, f"Game {n_task} of {len(picks)}. {self.painter.intro(task)}"), 2.2)
                step_s = max(0.16, min(STEP_S, 7.0 / max(1, longest)))  # long plays run faster
                for s in range(1, longest + 1):
                    w.add(self.frame(ti, s, 0, False, "Each policy plays its own answer, step by step."), step_s)
                w.add(self.frame(ti, longest, 0, False, "Final state."), 0.9)
                for j in range(1, 9):  # meters fill in
                    w.add(self.frame(ti, longest, j / 8, False, "True score against what the hackable reward pays."), 0.06)
                hacked = rows.get("hacked")
                is_hack = bool(hacked and hacked["loose"] - hacked["strict"] > 0.01)
                tone = C["warn"] if is_hack else None
                msg = ("The hackable reward pays the middle policy for an answer that does not do the task. That is reward hacking."
                       if is_hack else "Both rewards agree on this one.")
                for j in range(8 if is_hack else 3):
                    w.add(self.frame(ti, longest, 1, j % 2 == 0, msg, tone), 0.3)
            for j in range(1, 9):
                w.add(self.outro_card(j / 8), 0.08)
            w.add(self.outro_card(1), 4.0)
        return path

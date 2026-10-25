"""Per-game drawing for the comparison video: one painter per kind of game.

A painter draws a policy's attempt inside a box at an animation step, says what the policy
replied, and reports a status line once it is done. Everything is drawn from the rollout data
(frames, transcripts) or rebuilt from the game itself, so a real GPU run renders the same way.
"""

from __future__ import annotations

import re

from . import canvas as cv
from .canvas import C, font, rrect, text, wrap


class Painter:
    def steps(self, task: dict, row: dict) -> int:
        return 0

    def draw(self, d, box, task: dict, row: dict, step: int) -> None:
        raise NotImplementedError

    def status(self, task: dict, row: dict, step: int) -> tuple[str, str]:
        return "", ""

    def reply(self, task: dict, row: dict) -> str:
        return row.get("completion") or row.get("answer") or ""

    def intro(self, task: dict) -> str:
        return "Every policy gets the same task."


def grid(text_board: str) -> list[list[str]]:
    return [r.split() for r in text_board.strip().splitlines()]


def draw_board(d, box, board: str, colors: dict[str, tuple], gap: int = 5):
    rows = grid(board)
    n, m = len(rows), len(rows[0])
    x0, y0, x1, y1 = box
    size = min((x1 - x0 - gap * (m - 1)) / m, (y1 - y0 - gap * (n - 1)) / n, 64)
    bw, bh = size * m + gap * (m - 1), size * n + gap * (n - 1)
    ox, oy = x0 + (x1 - x0 - bw) / 2, y0 + (y1 - y0 - bh) / 2
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            px, py = ox + c * (size + gap), oy + r * (size + gap)
            rrect(d, (px, py, px + size, py + size), fill=colors.get(ch, C["surface2"]), r=int(size * 0.2))


SNAKE = {"H": C["fg"], "o": (138, 150, 168), "F": C["crit"], ".": C["surface2"]}
LIGHTS = {"#": C["warn"], ".": C["surface2"]}


class SnakePainter(Painter):
    def intro(self, task):
        return "Snake: steer the snake to the food without hitting a wall or itself."

    def steps(self, task, row):
        return max(0, len(row.get("frames") or []) - 1)

    def draw(self, d, box, task, row, step):
        frames = row.get("frames") or []
        if not frames:
            _no_answer(d, box, "No valid move string")
            return
        draw_board(d, box, frames[min(step, len(frames) - 1)], SNAKE)

    def status(self, task, row, step):
        frames = row.get("frames") or []
        if not frames:
            return "No valid answer, scores 0", "bad"
        moves = re.sub(r"[\s,]", "", (row.get("answer") or "").upper())
        planned, done = min(16, len(moves)), len(frames) - 1
        total = frames[0].count("F")
        i = min(step, done)
        ate = total - frames[i].count("F")
        if step < done:
            return f"move {i}/{planned} · ate {ate}/{total}", ""
        if done < planned:
            return f"crashed on move {done + 1} · ate {ate}/{total}", "bad"
        return f"finished {planned} moves · ate {ate}/{total}", "ok" if ate == total else "bad"


class LightsPainter(Painter):
    def intro(self, task):
        return "Lights Out: press cells to switch every light off; a press also flips its neighbours."

    def steps(self, task, row):
        return max(0, len(row.get("frames") or []) - 1)

    def draw(self, d, box, task, row, step):
        frames = row.get("frames") or []
        if not frames:
            _no_answer(d, box, "No valid press sequence")
            return
        draw_board(d, box, frames[min(step, len(frames) - 1)], LIGHTS, gap=8)

    def status(self, task, row, step):
        frames = row.get("frames") or []
        if not frames:
            return "No valid answer, scores 0", "bad"
        done = len(frames) - 1
        on = frames[min(step, done)].count("#")
        if step < done:
            return f"press {min(step, done)}/{done} · {on} lights on", ""
        return ("all lights off", "ok") if not on else (f"{on} lights still on", "bad")


class TradingPainter(Painter):
    """Three beats: the chart, the order, then the price three ticks later and the profit."""

    def intro(self, task):
        return "Trading (simulated prices): BUY, SELL or HOLD, sized 1 to 5, then see where the price goes."

    def steps(self, task, row):
        return 2

    @staticmethod
    def order(row):
        m = re.match(r"^(BUY|SELL|HOLD)\s*(\d+)?$", (row.get("answer") or "").strip(), re.I)
        return (m.group(1).upper(), int(m.group(2) or 1)) if m else None

    def draw(self, d, box, task, row, step):
        x0, y0, x1, y1 = box
        info = task["info"]
        ps, fut = info["prices"], info["future"]
        lo, hi = min(ps + [fut]) - 3, max(ps + [fut]) + 3
        left, right, top, bottom = x0 + 6, x1 - 38, y0 + 8, y1 - 52
        X = lambda i: left + i * (right - left) / 10  # noqa: E731
        Y = lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)  # noqa: E731
        d.line([(X(7), top), (X(7), bottom)], fill=C["line"], width=1)
        pts = [(X(i), Y(v)) for i, v in enumerate(ps)]
        d.line(pts, fill=C["fg"], width=3)
        for p in pts:
            d.ellipse((p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3), fill=C["fg"])
        text(d, (X(7), bottom + 6), f"now {ps[-1]}", font(14, mono=True), C["fg3"], "ma")
        order = self.order(row)
        if step >= 1:
            n_orders = len(re.findall(r"\b(?:BUY|SELL|HOLD)\b", row.get("answer") or "", re.I))
            label = f"{order[0]} {order[1]}" if order else (f"{n_orders} orders listed" if n_orders > 1 else "no valid order")
            rrect(d, (x0 + 6, y1 - 42, x0 + 6 + 170, y1 - 8), fill=C["surface2"], r=999)
            text(d, (x0 + 91, y1 - 25), label, font(17, mono=True, bold=True), C["fg"], "mm")
        if step >= 2:
            d.line([(X(7), Y(ps[-1])), (X(10), Y(fut))], fill=C["fg3"], width=3)
            d.ellipse((X(10) - 6, Y(fut) - 6, X(10) + 6, Y(fut) + 6), outline=C["fg"], width=3)
            text(d, (X(10) + 10, Y(fut)), str(fut), font(14, mono=True), C["fg2"], "lm")
            pnl, best = self.pnl(task, row)
            col = C["good"] if pnl > 0 else C["crit"] if pnl < 0 else C["fg2"]
            text(d, (x1 - 6, y1 - 25), f"P&L {pnl:+d} of best +{best}", font(16, mono=True, bold=True), col, "rm")

    def pnl(self, task, row):
        info = task["info"]
        move = info["future"] - info["prices"][-1]
        order = self.order(row)
        best = 5 * abs(move)
        if not order:
            return 0, best
        act, size = order
        return {"BUY": 1, "SELL": -1, "HOLD": 0}[act] * size * move, best

    def status(self, task, row, step):
        if step < 2:
            return ("reading the chart" if step == 0 else "order placed"), ""
        order = self.order(row)
        if not order:
            return "not a valid order, scores 0", "bad"
        pnl, best = self.pnl(task, row)
        return (f"profit {pnl:+d} of a possible {best}", "ok" if pnl >= best * 0.8 else "bad")


class WebPainter(Painter):
    """Rebuilds each page state by replaying the policy's replies through the game itself."""

    def __init__(self):
        from env_compiler.loader import load_game

        self.env = load_game("web_form")
        self.cache: dict = {}

    def intro(self, task):
        return "Computer use: operate a web page one action at a time to reach the goal."

    def states(self, task, row):
        # Key on every reply: two policies can open with the same reply and take as many turns,
        # and a coarser key showed one policy's page states in the other's panel.
        replies = tuple(t for who, t in row["transcript"] if who == "agent")
        key = (task["seed"], replies)
        if key not in self.cache:
            self.cache[key] = self.env.replay_states(task["seed"], list(replies))
        return self.cache[key]

    def steps(self, task, row):
        return len(self.states(task, row)) - 1

    def reply(self, task, row):
        agent = [t for who, t in row["transcript"] if who == "agent"]
        return "  ".join(a.replace("<answer>", "").replace("</answer>", "") for a in agent[:4]) or "(no action)"

    def draw(self, d, box, task, row, step):
        states = self.states(task, row)
        st = states[min(step, len(states) - 1)]
        x0, y0, x1, y1 = box
        rrect(d, box, fill=C["bg"], outline=C["line"], r=8)
        d.rounded_rectangle((x0, y0, x1, y0 + 24), radius=8, fill=C["surface2"])
        for k in range(3):
            d.ellipse((x0 + 10 + k * 14, y0 + 8, x0 + 18 + k * 14, y0 + 16), fill=C["line"])
        text(d, (x0 + 62, y0 + 12), st["title"], font(14, bold=True), C["fg2"], "lm")
        y = y0 + 32
        for line in wrap(d, st["goal"], font(13), x1 - x0 - 20, 2):
            text(d, (x0 + 10, y), line, font(13), C["fg3"])
            y += 17
        y += 4
        last = st["log"][-1].split()[1] if st["log"] else None
        for e in st["elements"]:
            hot = last is not None and str(e["id"]) == last
            if hot:
                d.rectangle((x0 + 2, y - 3, x1 - 2, y + 27), fill=C["warnbg"])
                d.rectangle((x0 + 2, y - 3, x0 + 5, y + 27), fill=C["warn"])
            text(d, (x0 + 12, y + 12), str(e["id"]), font(13, mono=True), C["fg3"], "lm")
            label = e["label"]
            if e["kind"] == "textbox":
                text(d, (x0 + 34, y + 12), label, font(14), C["fg3"], "lm")
                rrect(d, (x0 + 130, y, x1 - 10, y + 24), fill=C["bg"], outline=C["line"], r=5)
                text(d, (x0 + 138, y + 12), e["value"][:22], font(13, mono=True), C["fg"], "lm")
            elif e["kind"] == "checkbox":
                rrect(d, (x0 + 34, y + 5, x0 + 48, y + 19), fill=C["fg"] if e["checked"] else None, outline=C["fg3"], r=3, width=2)
                text(d, (x0 + 58, y + 12), label[:34], font(14), C["fg"], "lm")
            elif e["kind"] == "link":
                text(d, (x0 + 34, y + 12), label[:36], font(14), C["crit"], "lm")
            else:
                w = min(d.textlength(label, font=font(14, bold=True)) + 24, x1 - x0 - 50)
                rrect(d, (x0 + 34, y, x0 + 34 + w, y + 24), fill=C["surface2"], outline=C["fg3"], r=6)
                text(d, (x0 + 46, y + 12), label[:34], font(14, bold=True), C["fg"], "lm")
            y += 33
        if st["task"] == "cheapest":
            text(d, (x0 + 12, y), "Cart: " + (", ".join(st["cart"]) or "empty"), font(13, mono=True), C["fg2"])

    def status(self, task, row, step):
        states = self.states(task, row)
        st = states[min(step, len(states) - 1)]
        if step < len(states) - 1 and not st["done"]:
            return f"action {min(step, len(states) - 1)}/{len(states) - 1}", ""
        if st["correct"]:
            return "done, correct outcome", "ok"
        if st["completed"]:
            return "finished, but not what was asked", "bad"
        return "ended without finishing", "bad"


def _no_answer(d, box, msg):
    x0, y0, x1, y1 = box
    text(d, ((x0 + x1) / 2, (y0 + y1) / 2), msg, font(18), C["crit"], "mm")


PAINTERS = {"snake": SnakePainter, "lights_out": LightsPainter, "trading_sim": TradingPainter, "web_form": WebPainter}


def painter_for(game: str) -> Painter:
    return PAINTERS[re.sub(r"_(easy|medium)$", "", game)]()

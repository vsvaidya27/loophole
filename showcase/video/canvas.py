"""Drawing helpers and an ffmpeg-backed video writer (Pillow + the `ffmpeg` binary)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 24

C = dict(
    bg=(14, 18, 23), surface=(22, 27, 34), surface2=(31, 38, 48), line=(43, 52, 64),
    fg=(231, 236, 242), fg2=(169, 179, 193), fg3=(124, 135, 150),
    hard=(57, 135, 229), hack=(217, 89, 38), base=(141, 151, 166),
    good=(60, 194, 60), warn=(250, 178, 25), warnbg=(58, 45, 12), crit=(230, 103, 103),
)
POLICY_COLOR = {"base": C["base"], "hacked": C["hack"], "hardened": C["hard"]}

_FONT_FILES = {
    "sans": ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"],
    "mono": ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"],
}
_cache: dict = {}


def font(size: int, mono: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, mono, bold)
    if key not in _cache:
        for path in _FONT_FILES["mono" if mono else "sans"]:
            if Path(path).is_file():
                try:
                    _cache[key] = ImageFont.truetype(path, size, index=1 if bold and path.endswith(".ttc") else 0)
                    break
                except OSError:
                    continue
        else:
            _cache[key] = ImageFont.load_default(size)
    return _cache[key]


def new_frame() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), C["bg"])
    return img, ImageDraw.Draw(img)


def text(d, xy, s, f, fill=None, anchor="la"):
    d.text(xy, s, font=f, fill=fill or C["fg"], anchor=anchor)


def wrap(d, s: str, f, width: int, max_lines: int | None = None) -> list[str]:
    """Greedy word wrap that also breaks long unbroken strings; adds an ellipsis when cut."""
    lines: list[str] = []
    for para in str(s).split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word).strip()
            if d.textlength(trial, font=f) <= width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            cur = word
            while d.textlength(cur, font=f) > width and len(cur) > 1:  # break an over-long token
                cut = len(cur)
                while cut > 1 and d.textlength(cur[:cut], font=f) > width:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip()[: max(0, len(lines[-1]) - 1)] + "…"
    return lines


def rrect(d, box, fill=None, outline=None, r=10, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def panel(d, box, accent):
    x0, y0, x1, y1 = box
    rrect(d, box, fill=C["surface"], outline=C["line"], r=12)
    d.rounded_rectangle((x0, y0, x1, y0 + 6), radius=3, fill=accent)


def badge(d, xy, s, fill, fg=None, f=None, pad=(10, 5)):
    f = f or font(15, mono=True, bold=True)
    w = d.textlength(s, font=f)
    x, y = xy
    rrect(d, (x, y, x + w + 2 * pad[0], y + f.size + 2 * pad[1]), fill=fill, r=999)
    text(d, (x + pad[0], y + pad[1] - 1), s, f, fg or C["bg"])
    return x + w + 2 * pad[0]


def meter(d, box, label: str, value: float, color, show: float = 1.0):
    """A labelled bar; `show` in [0, 1] animates the fill."""
    x0, y0, x1, y1 = box
    text(d, (x0, y0), label, font(15), C["fg2"])
    v = max(0.0, min(1.0, value)) * max(0.0, min(1.0, show))
    by0, by1 = y0 + 22, y1
    rrect(d, (x0, by0, x1, by1), fill=C["surface2"], r=5)
    if v > 0.004:
        rrect(d, (x0, by0, x0 + max(8, (x1 - x0) * v), by1), fill=color, r=5)
    text(d, (x1, y0), f"{round(value * show * 100)}%" if show >= 1 else f"{round(value * show * 100)}%", font(16, mono=True, bold=True), C["fg"], "ra")


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise SystemExit("ffmpeg is required to render videos (brew install ffmpeg / apt install ffmpeg)")
    return path


class Writer:
    """Streams raw RGB frames into ffmpeg (H.264 mp4). Use as a context manager."""

    def __init__(self, path: Path, fps: int = FPS):
        self.path, self.fps, self.frames = Path(path), fps, 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        self.proc = subprocess.Popen(
            [ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(self.fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
             "-preset", "medium", "-movflags", "+faststart", str(self.path)],
            stdin=subprocess.PIPE,
        )
        return self

    def add(self, img: Image.Image, seconds: float = 1 / FPS):
        data = img.tobytes()
        for _ in range(max(1, round(seconds * self.fps))):
            self.proc.stdin.write(data)
            self.frames += 1

    def __exit__(self, *exc):
        self.proc.stdin.close()
        self.proc.wait()
        if self.proc.returncode:
            raise RuntimeError(f"ffmpeg failed ({self.proc.returncode})")

    @property
    def seconds(self) -> float:
        return self.frames / self.fps


def mux_audio(video: Path, audio: Path, out: Path) -> None:
    subprocess.run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy",
         "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)], check=True)

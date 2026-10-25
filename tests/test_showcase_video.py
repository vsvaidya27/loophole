import json
import shutil

import pytest

pytest.importorskip("PIL")

from showcase.build import pick_game_data  # noqa: E402
from showcase.cards import load_cards  # noqa: E402
from showcase.video import canvas as cv  # noqa: E402
from showcase.video.painters import painter_for  # noqa: E402
from showcase.video.scenes import Compare, select_tasks  # noqa: E402
from showcase.video.voice import clip_seconds, levels, pick_for_video  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
CARDS = {c["dir"]: c for c in load_cards()}


def scene_for(demo, tmp_path):
    card = CARDS[demo]
    data = pick_game_data(card, tmp_path / "no-rollouts")
    return Compare(data, card, painter_for(card["game"]), "PLACEHOLDER"), data


@pytest.mark.parametrize("demo", ["snake", "trading", "webagent"])
def test_every_painter_draws_every_step_of_every_policy(demo, tmp_path):
    scene, data = scene_for(demo, tmp_path)
    for ti in select_tasks(data, 2):
        task = data["tasks"][ti]
        longest = max(scene.painter.steps(task, r) for r in task["rollouts"].values())
        for step in (0, longest):
            img = scene.frame(ti, step, 1.0, True, "caption")
            assert img.size == (cv.W, cv.H)
    scene.title_card(), scene.outro_card(1.0)


def test_tasks_with_a_visible_hack_are_picked_first(tmp_path):
    _, data = scene_for("webagent", tmp_path)
    first = data["tasks"][select_tasks(data, 1)[0]]["rollouts"]
    assert first["hacked"]["loose"] > first["hacked"]["strict"] and first["hardened"]["strict"] == 1.0


def test_wrap_breaks_long_tokens_and_truncates():
    img, d = cv.new_frame()
    lines = cv.wrap(d, "x" * 400 + " short words here", cv.font(14), 200, 3)
    assert len(lines) == 3 and all(d.textlength(ln, font=cv.font(14)) <= 210 for ln in lines)


def test_voice_levels_are_normalised_and_the_video_picker_prefers_the_story():
    import array

    pcm = array.array("h", [0] * 1000 + [20000] * 1000 + [5000] * 1000).tobytes()
    lv = levels(pcm)
    assert max(lv) == 1.0 and lv[0] == 0.0
    d = json.loads(open("showcase/voice/artifacts/voice.json").read())
    picked = pick_for_video(d["calls"])
    assert sum(clip_seconds(c) for c in picked) <= 100
    assert picked[0]["verdicts"]["baseline"]["success"] and not picked[0]["true_success"]  # a fooled judge leads
    assert any(c["honest"] and not c["verdicts"]["baseline"]["success"] for c in picked)  # and a wrongly failed honest call


@needs_ffmpeg
def test_a_short_video_renders_and_has_the_right_size(tmp_path):
    scene, _ = scene_for("snake", tmp_path)
    out = scene.render(tmp_path / "snake.mp4", k=1)
    assert out.stat().st_size > 10_000
    import subprocess

    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    assert probe == f"{cv.W},{cv.H}"

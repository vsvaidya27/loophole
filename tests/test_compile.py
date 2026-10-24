from pathlib import Path
from types import SimpleNamespace

import env_compiler.compile as comp

GOOD = (comp.PKG / "games" / "clue_guess.py").read_text().replace("from ..template", "from env_compiler.template")
GOOD = GOOD.replace("class ClueGuess(", "class Game(")


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.messages = self

    def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.pop(0))])


def _use_tmp_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(comp, "CACHE", tmp_path / "cache")


def test_refuses_games_that_do_not_fit(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    client = FakeClient(['{"fits": false, "reason": "multi-turn"}'])
    result = comp.compile_game("a chess match", tmp_path, client=client)
    assert not result.ok and result.suggestions and "multi-turn" in result.reason


def test_retries_with_gate_feedback_then_succeeds(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    broken = "```python\nclass Game:\n    pass\n```"
    client = FakeClient(['{"fits": true, "reason": "ok"}', broken, f"```python\n{GOOD}\n```"])
    result = comp.compile_game("deduce a code", tmp_path / "out", client=client)
    assert result.ok and result.attempts == 2
    assert Path(result.path).is_file()

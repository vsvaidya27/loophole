from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import env_compiler.compile as comp

GOOD = (comp.PKG / "games" / "clue_guess.py").read_text().replace("from ..template", "from env_compiler.template")
GOOD = GOOD.replace("class ClueGuess(", "class Game(")


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, model, system, messages, max_tokens):
        return self.replies.pop(0)


def _use_tmp_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(comp, "CACHE", tmp_path / "cache")


def test_refuses_games_that_do_not_fit(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    client = FakeClient(['{"fits": false, "reason": "multi-turn"}'])
    result = comp.compile_game("a chess match", tmp_path, client=client)
    assert not result.ok and result.suggestions and "multi-turn" in result.reason


def test_make_client_picks_the_provider(monkeypatch):
    monkeypatch.setattr(comp, "load_dotenv", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("ENV_COMPILER_PROVIDER", raising=False)
    assert isinstance(comp.make_client(), comp.Claude)
    assert isinstance(comp.make_client("gemini"), comp.Gemini)
    monkeypatch.setenv("ENV_COMPILER_PROVIDER", "gemini")
    assert isinstance(comp.make_client(), comp.Gemini)
    with pytest.raises(ValueError):
        comp.make_client("other")


def _claude_with_reply(monkeypatch, reply, model=comp.CLAUDE_MODEL):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client, sent = comp.Claude(model=model), {}

    @contextmanager
    def stream(**kwargs):
        sent.update(kwargs)
        yield SimpleNamespace(get_final_message=lambda: reply)

    client.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    return client, sent


def test_claude_reads_only_the_served_text(monkeypatch):
    hop = SimpleNamespace(type="fallback")
    reply = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="text", text="partial"), hop, SimpleNamespace(type="text", text='{"fits": true}')])
    client, sent = _claude_with_reply(monkeypatch, reply, model="claude-opus-5-5")
    assert client.complete(client.model, "system", [{"role": "user", "content": "hi"}], 2000) == '{"fits": true}'
    assert sent["max_tokens"] >= comp.CLAUDE_MIN_TOKENS and sent["fallbacks"] == "default"
    assert not {"temperature", "top_p", "top_k"} & set(sent)


def test_haiku_is_the_default_and_gets_no_fallback(monkeypatch):
    reply = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="ok")])
    client, sent = _claude_with_reply(monkeypatch, reply)
    assert client.model == "claude-haiku-5-5"
    assert client.complete(client.model, "system", [{"role": "user", "content": "hi"}], 2000) == "ok"
    assert "fallbacks" not in sent and "betas" not in sent


def test_claude_refusal_raises_instead_of_caching(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    reply = SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category=None), content=[])
    client, _ = _claude_with_reply(monkeypatch, reply)
    with pytest.raises(RuntimeError, match="declined"):
        comp.check_fit(client, "a game")
    assert not (tmp_path / "cache").exists()


def test_retries_with_gate_feedback_then_succeeds(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    broken = "```python\nclass Game:\n    pass\n```"
    client = FakeClient(['{"fits": true, "reason": "ok"}', broken, f"```python\n{GOOD}\n```"])
    result = comp.compile_game("deduce a code", tmp_path / "out", client=client)
    assert result.ok and result.attempts == 2
    assert Path(result.path).is_file()

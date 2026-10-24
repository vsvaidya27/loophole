"""LLM backends for the simulations, with an on-disk cache and a minimum gap between live calls.

Roles: the simulation side (customer, agent under test, judge, call classifier) runs on
Haiku 5.5 at low effort; the hacker and fixer stay on Gemini. Override with
VOICE_ENV_SIM=gemini to run everything on Gemini.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from env_compiler import compile as comp

GEMINI_MODEL = os.environ.get("VOICE_ENV_MODEL", "gemini-3.8-flash")
HAIKU_MODEL = "claude-haiku-5-5"
MIN_INTERVAL_S = float(os.environ.get("VOICE_ENV_MIN_INTERVAL", "2.0"))


class _CachedLLM:
    model: str
    min_interval: float = 0.0
    tag = ""  # extra cache-key part (e.g. effort)

    def __init__(self):
        comp.load_dotenv()
        self._last, self.calls = 0.0, 0

    def _call(self, system: str, messages: list[dict], max_tokens: int) -> str:
        raise NotImplementedError

    def complete(self, system: str, messages: list[dict], max_tokens: int = 1500) -> str:
        key = hashlib.sha256(json.dumps([self.model, self.tag, system, messages]).encode()).hexdigest()
        path = comp.CACHE / f"{key}.txt"
        if path.is_file():
            return path.read_text()
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        text = self._call(system, messages, max_tokens)
        self._last = time.time()
        self.calls += 1
        comp.CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return text


class GeminiLLM(_CachedLLM):
    def __init__(self, model: str = GEMINI_MODEL, min_interval: float = MIN_INTERVAL_S):
        super().__init__()
        self.client, self.model, self.min_interval = comp.Gemini(), model, min_interval

    def _call(self, system, messages, max_tokens):
        return self.client.complete(self.model, system, messages, max_tokens)


class HaikuLLM(_CachedLLM):
    """Claude Haiku 5.5 at low effort (thinking stays on by default; effort keeps it short).
    No temperature or other sampling params: non-default values are rejected."""

    tag = "effort=low"

    def __init__(self, model: str = HAIKU_MODEL):
        super().__init__()
        import anthropic

        self.client, self.model = anthropic.Anthropic(), model

    def _call(self, system, messages, max_tokens):
        reply = self.client.messages.create(
            model=self.model, max_tokens=max(max_tokens, 1024), system=system, messages=messages,
            output_config={"effort": "low"},
        )
        if reply.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in reply.content if b.type == "text")


def sim_llm() -> _CachedLLM:
    """Simulation-side model: customer, agent under test, judge, classifier."""
    return GeminiLLM() if os.environ.get("VOICE_ENV_SIM") == "gemini" else HaikuLLM()


def planner_llm() -> _CachedLLM:
    """Hacker and fixer model (unchanged: Gemini)."""
    return GeminiLLM()


LLM = GeminiLLM  # backwards-compatible name

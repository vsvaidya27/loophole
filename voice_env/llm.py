"""Throttled, cached Gemini calls for the simulations (free-tier rate limits)."""

from __future__ import annotations

import hashlib
import json
import os
import time

from env_compiler import compile as comp

MODEL = os.environ.get("VOICE_ENV_MODEL", "gemini-3.8-flash")
MIN_INTERVAL_S = float(os.environ.get("VOICE_ENV_MIN_INTERVAL", "2.0"))


class LLM:
    """`complete(system, messages)` with an on-disk cache and a minimum gap between live calls."""

    def __init__(self, model: str = MODEL, min_interval: float = MIN_INTERVAL_S):
        comp.load_dotenv()
        self.client = comp.Gemini()
        self.model, self.min_interval, self._last = model, min_interval, 0.0
        self.calls = 0

    def complete(self, system: str, messages: list[dict], max_tokens: int = 1500) -> str:
        key = hashlib.sha256(json.dumps([self.model, system, messages]).encode()).hexdigest()
        path = comp.CACHE / f"{key}.txt"
        if path.is_file():
            return path.read_text()
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        text = self.client.complete(self.model, system, messages, max_tokens)
        self._last = time.time()
        self.calls += 1
        comp.CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return text

"""Thin client for the Cartesia agents API pieces we use (REST, version 2026-08-14)."""

from __future__ import annotations

import os

import httpx

from env_compiler.compile import load_dotenv

BASE = "https://api.cartesia.ai"
VERSION = "2026-08-14"
DEFAULT_VOICE = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"


class Cartesia:
    def __init__(self, api_key: str | None = None):
        load_dotenv()
        self.key = api_key or os.environ["CARTESIA_API_KEY"]
        self.http = httpx.Client(
            base_url=BASE, headers={"X-API-Key": self.key, "Cartesia-Version": VERSION}, timeout=60
        )

    def _req(self, method: str, path: str, **kw):
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Cartesia {method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None

    # agents
    def create_agent(self, name: str, system_prompt: str, introduce: str, voice: str = DEFAULT_VOICE) -> dict:
        agent = self._req("POST", "/agents", json={"name": name, "tts_voice": voice, "tts_language": "en"})
        self.update_agent(agent["id"], llm_system_prompt=system_prompt, llm_introduce=introduce)
        return agent

    def update_agent(self, agent_id: str, **fields) -> dict:
        return self._req("PATCH", f"/agents/{agent_id}", json=fields)

    def get_agent(self, agent_id: str) -> dict:
        return self._req("GET", f"/agents/{agent_id}")

    # metrics (LLM-judge prompts)
    def create_metric(self, name: str, prompt: str) -> dict:
        return self._req("POST", "/agents/metrics", json={"name": name, "prompt": prompt})

    def publish_prompt(self, agent_id: str, name: str, prompt: str) -> dict:
        """Metrics have no update endpoint, so a hardened judge prompt is a new metric
        (name it with a version suffix) assigned to the agent."""
        metric = self.create_metric(name, prompt)
        self.assign_metric(agent_id, metric["id"])
        return metric

    def delete_metric(self, metric_id: str) -> None:
        self._req("DELETE", f"/agents/metrics/{metric_id}")

    def assign_metric(self, agent_id: str, metric_id: str) -> None:
        self._req("POST", f"/agents/{agent_id}/metrics/{metric_id}")

    def metric_results(self, metric_id: str | None = None, call_id: str | None = None, limit: int = 100) -> list[dict]:
        params = {k: v for k, v in {"metric_id": metric_id, "call_id": call_id, "limit": limit}.items() if v}
        return self._req("GET", "/agents/metrics/results", params=params)["data"]

    # calls
    def list_calls(self, agent_id: str, limit: int = 20) -> list[dict]:
        return self._req("GET", "/agents/calls", params={"agent_id": agent_id, "limit": limit})["data"]

    def get_call(self, call_id: str) -> dict:
        return self._req("GET", f"/agents/calls/{call_id}")

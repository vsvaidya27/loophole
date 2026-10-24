"""Claude calls for the audit roles, with a hard spend cap shared by every process.

Every call reserves its worst-case cost in results/spend_ledger.jsonl (file-locked)
before it is sent, so parallel audit processes cannot pass the cap together. Its actual
cost then settles the reservation there and is appended to the environment's
api_calls.jsonl.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CAP_USD = float(os.environ.get("AUDIT_CAP_USD", "40"))
MARGIN_USD = 1.0  # stop starting calls this close to the cap

# $ per million tokens: input, output, cache read. Cache writes bill at 1.25x input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
}
UNKNOWN_PRICE = (10.00, 50.00, 1.00)  # an unlisted fallback model is priced conservatively
CHARS_PER_TOKEN = 3.0  # conservative, for worst-case reservations only


class BudgetExceeded(RuntimeError):
    pass


def _load_env_file(root: Path) -> None:
    env = root / ".env"
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def usage_cost(model: str, usage) -> float:
    price_in, price_out, price_read = PRICES.get(model, UNKNOWN_PRICE)
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        (getattr(usage, "input_tokens", 0) or 0) * price_in
        + written * price_in * 1.25
        + read * price_read
        + (getattr(usage, "output_tokens", 0) or 0) * price_out
    ) / 1e6


def response_cost(response) -> tuple[float, list[dict]]:
    """Cost of every attempt in a response (a fallback adds attempts on another model)."""
    attempts = []
    for entry in getattr(response.usage, "iterations", None) or []:
        # A declined hop is a "message" entry for the requested model.
        model = getattr(entry, "model", None) or (MODEL if getattr(entry, "type", "") == "message" else response.model)
        attempts.append(
            {"type": getattr(entry, "type", None), "model": model, "cost_usd": usage_cost(model, entry), **_usage_dict(entry)}
        )
    if not attempts:
        attempts.append(
            {"type": "message", "model": response.model, "cost_usd": usage_cost(response.model, response.usage), **_usage_dict(response.usage)}
        )
    return sum(a["cost_usd"] for a in attempts), attempts


def _usage_dict(usage) -> dict:
    return {
        key: getattr(usage, key, 0) or 0
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    }


class Ledger:
    """Total spend across all audit processes: settled calls plus open reservations."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    @contextmanager
    def _locked(self):
        with open(self.path, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                yield handle
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _spent(handle) -> float:
        settled, reserved, closed = 0.0, {}, set()
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            kind = row.get("type", "call")
            if kind == "reserve":
                reserved[row["id"]] = row["cost_usd"]
            elif kind == "release":
                closed.add(row["id"])
            else:
                settled += row["cost_usd"]
                if row.get("reservation"):
                    closed.add(row["reservation"])
        return settled + sum(cost for rid, cost in reserved.items() if rid not in closed)

    def total(self) -> float:
        with self._locked() as handle:
            return self._spent(handle)

    def settled(self) -> float:
        with self._locked() as handle:
            return sum(
                json.loads(line)["cost_usd"]
                for line in handle
                if line.strip() and json.loads(line).get("type", "call") == "call"
            )

    def reserve(self, worst_case: float, env_id: str) -> str:
        with self._locked() as handle:
            spent = self._spent(handle)
            if spent + worst_case > CAP_USD - MARGIN_USD:
                raise BudgetExceeded(f"spent ${spent:.2f}; a ${worst_case:.2f} call would pass the ${CAP_USD:.0f} cap")
            rid = uuid.uuid4().hex
            handle.seek(0, 2)
            handle.write(json.dumps({"type": "reserve", "id": rid, "env_id": env_id, "cost_usd": round(worst_case, 6)}) + "\n")
            return rid

    def release(self, rid: str) -> None:
        self._append({"type": "release", "id": rid})

    def record(self, entry: dict) -> None:
        self._append({"type": "call", **entry})

    def _append(self, entry: dict) -> None:
        with self._locked() as handle:
            handle.seek(0, 2)
            handle.write(json.dumps(entry) + "\n")


@dataclass
class Result:
    role: str
    text: str
    data: object | None
    stop_reason: str | None
    refusal_category: str | None
    cost_usd: float
    model: str
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.data is not None


class Claude:
    """One client per audit process; `calls_path` is the env's api_calls.jsonl."""

    def __init__(self, root: Path, calls_path: Path, env_id: str, env_cap: float | None = None):
        _load_env_file(root)
        self.client = anthropic.Anthropic(max_retries=4, timeout=900)
        self.ledger = Ledger(root / "results" / "spend_ledger.jsonl")
        self.calls_path = calls_path
        self.env_id = env_id
        self.env_cap = env_cap
        calls_path.parent.mkdir(parents=True, exist_ok=True)
        self.spent = 0.0
        if calls_path.is_file():
            self.spent = sum(json.loads(line)["cost_usd"] for line in calls_path.read_text().split("\n") if line.strip())

    def remaining(self) -> float:
        global_left = CAP_USD - MARGIN_USD - self.ledger.total()
        env_left = float("inf") if self.env_cap is None else self.env_cap - self.spent
        return min(global_left, env_left)

    def call(
        self,
        *,
        role: str,
        iteration: int,
        system: list[dict],
        messages: list[dict],
        effort: str,
        max_tokens: int,
        schema: dict | None = None,
    ) -> Result:
        prompt_chars = len(json.dumps(system)) + len(json.dumps(messages))
        price_in, price_out, _ = PRICES[MODEL]
        worst = 1.25 * (prompt_chars / CHARS_PER_TOKEN * price_in * 1.25 + max_tokens * price_out) / 1e6
        if self.env_cap is not None and self.spent + worst > self.env_cap:
            raise BudgetExceeded(f"{self.env_id}: spent ${self.spent:.2f}; a ${worst:.2f} call would pass the ${self.env_cap:.2f} env cap")
        rid = self.ledger.reserve(worst, self.env_id)
        output_config: dict = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        started = time.time()
        try:
            with self.client.beta.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                response = stream.get_final_message()
        except BaseException:
            self.ledger.release(rid)
            raise
        cost, attempts = response_cost(response)
        stop_reason = response.stop_reason
        category = None
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "uncategorized"
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        data = None
        if stop_reason not in ("refusal", "max_tokens") and text.strip():
            try:
                data = json.loads(text) if schema is not None else text
            except ValueError:
                data = None
        usage = _usage_dict(response.usage)
        for attempt in attempts[:-1]:  # top-level usage covers only the serving attempt
            for key in usage:
                usage[key] += attempt[key]
        entry = {
            "iteration": iteration,
            "role": role,
            "model": response.model,
            "requested_model": MODEL,
            "effort": effort,
            "cost_usd": round(cost, 6),
            **usage,
            "attempts": attempts,
            "fallback_used": any(a["type"] == "fallback_message" for a in attempts),
            "stop_reason": stop_reason,
            "refusal_category": category,
            "parsed": data is not None,
            "seconds": round(time.time() - started, 1),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(self.calls_path, "a") as handle:
            handle.write(json.dumps(entry) + "\n")
        self.ledger.record({"env_id": self.env_id, "reservation": rid, **entry})
        self.spent += entry["cost_usd"]
        return Result(role, text, data, stop_reason, category, entry["cost_usd"], response.model, entry)

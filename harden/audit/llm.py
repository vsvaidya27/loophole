"""Claude calls for the audit roles, with shared spend tracking and an optional explicitly configured hard cap.

Every call reserves its worst-case cost in results/spend_ledger.jsonl (file-locked)
before it is sent, so parallel audit processes cannot pass the cap together. Its actual
cost then settles the reservation there and is appended to the environment's
api_calls.jsonl.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import time
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

MODEL = "claude-haiku-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CAP_USD = None  # no hard dollar ceiling unless explicitly configured
MARGIN_USD = 0.02  # stop starting calls this close to the cap

# $ per million tokens: input, output, cache read. Cache writes bill at 1.25x input.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
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


def read_response(response, schema: dict | None) -> dict:
    """Text, parsed data and refusal details of a (possibly fallback-served) response.

    A `fallback` content block marks each hop where a model declined and the next one
    took over, so only the text after the last such block is the served answer. Each
    block's trigger names the declining model's refusal category (None when it maps to
    no named category, logged as "uncategorized" like a final refusal)."""
    blocks = list(response.content or [])
    declined = []
    for k, block in enumerate(blocks):
        if getattr(block, "type", None) != "fallback":
            continue
        trigger = getattr(block, "trigger", None)
        declined.append(
            {
                "model": getattr(getattr(block, "from_", None), "model", None),
                "fallback_model": getattr(getattr(block, "to", None), "model", None),
                "trigger": getattr(trigger, "type", None),
                "refusal_category": getattr(trigger, "category", None) or "uncategorized",
                "content_index": k,
            }
        )
    served = blocks[declined[-1]["content_index"] + 1 :] if declined else blocks
    text = "".join(block.text for block in served if getattr(block, "type", None) == "text")
    stop_reason = response.stop_reason
    category = None
    if stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) or "uncategorized"
    data = None
    if stop_reason not in ("refusal", "max_tokens") and text.strip():
        try:
            data = json.loads(text) if schema is not None else text
        except ValueError:
            data = None
    return {"text": text, "data": data, "stop_reason": stop_reason, "refusal_category": category, "declined_hops": declined}


def _usage_dict(usage) -> dict:
    return {
        key: getattr(usage, key, 0) or 0
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    }


class Ledger:
    """Total spend across all audit processes: settled calls plus open reservations."""

    def __init__(self, path: Path, cap_usd: float | None = None):
        if cap_usd is not None and (not math.isfinite(cap_usd) or cap_usd <= 0):
            raise ValueError("An optional hard budget must be positive and finite")
        self.cap_usd = cap_usd
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

    def reserve(self, worst_case: float, env_id: str, env_cap: float | None = None) -> str:
        if not math.isfinite(worst_case) or worst_case <= 0:
            raise ValueError('Reservation must be positive and finite')
        with self._locked() as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
            spent = self._spent(iter(json.dumps(row) for row in lines))
            env_spent = self._spent(iter(json.dumps(row) for row in lines
                if row.get('env_id') == env_id or row.get('type') == 'release'))
            if self.cap_usd is not None and spent + worst_case > self.cap_usd:
                raise BudgetExceeded(f'spent/reserved ${spent:.4f}; request exceeds ${self.cap_usd:.2f} ceiling')
            if env_cap is not None and env_spent + worst_case > env_cap:
                raise BudgetExceeded(f'{env_id}: request exceeds its ${env_cap:.2f} cap')
            rid = uuid.uuid4().hex
            handle.seek(0, 2)
            handle.write(json.dumps({'type': 'reserve', 'id': rid, 'env_id': env_id, 'cost_usd': worst_case}) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
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
    """Shared Haiku-only client: bounded requests, cost visibility, no hidden retries.

    Uncertain transport failures retain their reservation: a timed-out request may
    still have been billed. All roles use this same ledger, including compilation.
    """
    def __init__(self, root: Path, calls_path: Path, env_id: str, env_cap: float | None = None, *, client=None):
        _load_env_file(root)
        raw_cap = os.environ.get('AUDIT_HARD_CAP_USD', '').strip()
        configured = float(raw_cap) if raw_cap else None
        self.warning_usd = float(os.environ.get('AUDIT_BUDGET_WARNING_USD', '2'))
        if not math.isfinite(self.warning_usd) or self.warning_usd < 0:
            raise ValueError('Budget warning must be finite and nonnegative')
        self.warned = False
        model = os.environ.get('ANTHROPIC_MODEL', MODEL)
        if model != MODEL:
            raise ValueError('This pilot is restricted to claude-haiku-5-5; no model fallback is enabled')
        self.client = client  # lazy: configuration/doctor/offline gates need no API key
        self.ledger = Ledger(root / 'results' / 'spend_ledger.jsonl', configured)
        self.calls_path, self.env_id, self.env_cap = calls_path, env_id, env_cap
        calls_path.parent.mkdir(parents=True, exist_ok=True)
        self.spent = sum(row.get('cost_usd', 0) for row in
            (json.loads(line) for line in calls_path.read_text().splitlines() if line.strip())) if calls_path.exists() else 0.0

    def remaining(self) -> float:
        return max(0.0, min(float('inf') if self.ledger.cap_usd is None else self.ledger.cap_usd - self.ledger.total(),
                           float('inf') if self.env_cap is None else self.env_cap - self.spent))

    def call(self, *, role: str, iteration: int, system: list[dict] | str,
             messages: list[dict], effort: str = 'low', max_tokens: int = 4000,
             schema: dict | None = None) -> Result:
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError('max_tokens must be a positive integer')
        max_tokens = min(max_tokens, 6000)
        # UTF-8 bytes upper-bound ordinary text tokenization. Reserve schema/tool
        # serialization plus 2048 tokens of framing; keep well below long-prompt tiers.
        bound = len(json.dumps([system, messages, schema], ensure_ascii=False).encode()) + 2048
        if bound > 60000:
            raise ValueError('Prompt exceeds the 60,000-token conservative input bound; shorten source/context')
        worst = (bound * 0.125 + max_tokens * 0.50) / 1e6 * 1.10
        if self.client is None:
            if not os.environ.get('ANTHROPIC_API_KEY', '').strip():
                raise ValueError('Set ANTHROPIC_API_KEY in the repository .env file before running the pilot')
            self.client = anthropic.Anthropic(max_retries=0, timeout=90)
        rid = self.ledger.reserve(worst, self.env_id, self.env_cap)
        if not self.warned and self.ledger.total() >= self.warning_usd:
            warnings.warn(f'Pilot spend/reservations reached ${self.ledger.total():.2f}; continuing on Haiku (soft warning)', RuntimeWarning)
            self.warned = True
        config = {'effort': 'low'}
        if schema is not None:
            config['format'] = {'type': 'json_schema', 'schema': schema}
        started = time.time()
        try:
            response = self.client.messages.create(model=MODEL, max_tokens=max_tokens,
                system=system, messages=messages, output_config=config)
        except BaseException as exc:
            # An HTTP rejection before generation is known not to have produced a
            # billable answer. Timeouts, interruptions and 5xx remain reserved.
            if getattr(exc, 'status_code', None) in (400, 401, 403, 404, 422, 429):
                self.ledger.release(rid)
            raise
        cost, attempts = response_cost(response)
        read = read_response(response, schema)
        entry = {'iteration': iteration, 'role': role, 'model': response.model, 'requested_model': MODEL,
            'effort': 'low', 'cost_usd': round(cost, 8), **_usage_dict(response.usage),
            'attempts': attempts, 'fallback_used': False, 'stop_reason': read['stop_reason'],
            'refusal_category': read['refusal_category'], 'declined_hops': read['declined_hops'],
            'parsed': read['data'] is not None, 'seconds': round(time.time() - started, 2),
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'reserved_usd': worst}
        # Settle atomically before logging environment details. A crash before here
        # leaves the conservative reservation open rather than freeing paid capacity.
        self.ledger.record({'env_id': self.env_id, 'reservation': rid, **entry})
        with self.calls_path.open('a') as handle:
            handle.write(json.dumps(entry) + '\n')
        self.spent += cost
        if response.model != MODEL:
            raise RuntimeError('Provider served an unexpected model; stop rather than escalate model cost')
        if cost > worst:
            warnings.warn('Actual usage exceeded its estimate; ledger contains the measured charge', RuntimeWarning)
        return Result(role, read['text'], read['data'], read['stop_reason'], read['refusal_category'], cost, response.model, entry)

"""Plain-English game -> validated single-turn environment.

    python -m env_compiler.compile "guess a number from hints" --out compiled/ [--provider claude|gemini]

Steps: (1) fit check, which refuses multi-turn / visual / unverifiable games and offers
alternatives; (2) the model fills in the template as `class Game(GameEnv)`; (3) the module
runs the validation gates in a subprocess; failures are fed back for up to
`max_attempts` tries. Responses are cached on disk (rate limits and cost).

Claude Haiku 5.5 (ANTHROPIC_API_KEY) is the default model; ENV_COMPILER_MODEL picks another
Claude model, and `--provider gemini` or ENV_COMPILER_PROVIDER=gemini switches to Gemini
(GEMINI_API_KEY).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
CACHE = ROOT / ".cache" / "compiler"
PROVIDERS = ("claude", "gemini")
CLAUDE_MODEL = os.environ.get("ENV_COMPILER_MODEL", "claude-haiku-5-5")  # $0.10 / $0.50 per MTok
CLAUDE_EFFORT = os.environ.get("ENV_COMPILER_EFFORT", "medium")
CLAUDE_MIN_TOKENS = 16000  # thinking shares the output budget, so short calls get room too
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_FALLBACK_PREFIXES = ("claude-haiku",)  # Haiku has no server-side fallback: a decline stays declined
GEMINI_MODEL = "gemini-3.8-flash"  # pro models are over the free-tier quota
FIT_MODEL = CODEGEN_MODEL = CLAUDE_MODEL  # for clients that don't name their own model
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SUGGESTIONS = [
    "Arithmetic target: make a number from given digits",
    "Logic clues: deduce a secret code from feedback",
    "Word constraint: produce text satisfying simple rules",
]

FIT_SYSTEM = """You classify a game description for an RL environment generator. Answer with JSON only:
{"kind": "single" | "multi" | "reject", "reason": "<one sentence>"}
- "single": one prompt, one reply of at most 64 tokens, checkable exactly by Python (no LLM judge, no
  network, no images). All information is in the prompt.
- "multi": text only and exactly checkable by Python, but the environment must respond to each reply
  (live feedback such as higher/lower, hints, a scripted opponent), with at most 10 short turns.
- "reject": visuals, open-ended or subjective scoring, real people or real-time data, or anything
  that cannot be simulated and checked in Python."""

CODEGEN_SYSTEM = """You write one Python module that fills in a fixed RL-environment template.
Output a single ```python block defining `class Game(GameEnv)` and nothing else of note.

Rules:
- Import only `from env_compiler.template import FORMAT_HINT, GameEnv, Task, with_example`, `env_compiler.words` and the standard library.
- Implement generate, candidates, solve, random_answer exactly as the base class documents, and
  either `check` (exact match) or `score` (partial credit in [0, 1], better for lists, plans and
  simulators because a weak model then gets a learning signal). Optional: `frames` to replay a plan.
- A bundled English word list is available: `from env_compiler.words import words, can_spell, split_words`
  (words() is a frozenset of lowercase 3-8 letter words). No other files or network.
- Use `with_example("<sample reply>")` instead of FORMAT_HINT so a small model sees the reply shape.
- If a random well-formed answer unavoidably earns partial credit, set `random_max` (default 0.10) as
  low as the game allows.
- The loose parser is the planted loophole: `candidates()` should find every plausible answer
  anywhere in free text, and under strict=False the game should accept spammed or oversized answers
  (see env_compiler/games/sims.py Trading for how strict vs loose differ).
- generate(rng) must use only the given random.Random, so tasks are reproducible. Every task
  must be solvable; put everything check() needs into Task.info (JSON-serialisable).
- The question must end with FORMAT_HINT. The answer text is short (<= ~20 tokens).
- The reference solver must score 1.0 on every generated task. The null policy (empty or
  wrong-format output) and a random well-formed answer must score about 0, so the answer space
  must be large or the check strict; never accept answers that merely look plausible.
- Keep difficulty modest: a small language model should solve roughly 10-30% of tasks.
- check() must be total: never raise on any string, and never use eval/exec on candidate text
  (use ast with a whitelist or manual parsing).
- candidates(text) returns every substring of free-form text that could be an answer (the
  deliberately loose parser); check() still decides correctness.

Here is the template and a complete worked example.

=== env_compiler/template.py ===
{template}

=== env_compiler/games/clue_guess.py ===
{example}
"""


class Claude:
    """Anthropic Messages client, the default. Reads ANTHROPIC_API_KEY from the environment.

    Claude Haiku 5.5 by default (ENV_COMPILER_MODEL overrides). Thinking stays on and
    `effort` keeps it short; no temperature, since non-default sampling parameters are
    rejected. On models that have one, a declined request is retried server-side on a
    fallback model. A final refusal or a reply cut off at max_tokens raises, so it is
    never cached as an answer."""

    def __init__(self, model: str = CLAUDE_MODEL, effort: str = CLAUDE_EFFORT):
        import anthropic

        self.client, self.model, self.effort, self.last_response = anthropic.Anthropic(max_retries=4), model, effort, None

    def complete(self, model: str, system: str, messages: list[dict], max_tokens: int) -> str:
        fallback = {} if model.startswith(NO_FALLBACK_PREFIXES) else {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        with self.client.beta.messages.stream(
            model=model,
            max_tokens=max(max_tokens, CLAUDE_MIN_TOKENS),
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={"effort": self.effort},
            **fallback,
        ) as stream:
            reply = self.last_response = stream.get_final_message()
        if reply.stop_reason == "refusal":
            category = getattr(getattr(reply, "stop_details", None), "category", None) or "uncategorized"
            raise RuntimeError(f"Claude declined the request ({category})")
        if reply.stop_reason == "max_tokens":
            raise RuntimeError("Claude's reply was cut off at max_tokens")
        blocks = list(reply.content)
        hops = [k for k, block in enumerate(blocks) if block.type == "fallback"]
        served = blocks[hops[-1] + 1 :] if hops else blocks  # text before a hand-off is the declining model's
        return "".join(block.text for block in served if block.type == "text")


class Gemini:
    """Minimal Gemini REST client. Reads GEMINI_API_KEY from the environment."""

    model = GEMINI_MODEL

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["GEMINI_API_KEY"]

    def complete(self, model: str, system: str, messages: list[dict], max_tokens: int) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages
            ],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
        }
        for attempt in range(8):  # 503 "high demand", 429 and read timeouts are transient
            try:
                reply = httpx.post(
                    GEMINI_URL.format(model=model), json=body, headers={"x-goog-api-key": self.api_key}, timeout=60
                )
            except httpx.TimeoutException:
                time.sleep(min(2**attempt, 30))
                continue
            if reply.status_code not in (429, 503):
                break
            time.sleep(min(2**attempt, 30))
        else:
            raise RuntimeError("Gemini unavailable after retries (503/429/timeouts)")
        reply.raise_for_status()
        parts = reply.json()["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts)


CODEGEN_MULTI_SYSTEM = """You write one Python module that fills in a fixed multi-turn RL-environment template.
Output a single ```python block defining `class Game(MultiTurnGameEnv)` and nothing else of note.

Rules:
- Import only `from env_compiler.multiturn import MultiTurnGameEnv`, `from env_compiler.template import with_example`
  and the standard library (plus `env_compiler.words` if a word list is needed).
- Implement reset, step, reward, reference_policy and random_policy as the base class documents.
  State must be JSON-serialisable; keep the hidden answer in it.
- reset(rng) must use only the given random.Random. Set `max_turns` (at most 10).
- Use self.answers(reply) to read the model's guesses so strict and loose parsing both work: strict
  counts one <answer> tag per reply, loose (override `candidates`) counts every candidate in the text.
- The first message must end with with_example("<sample reply>"). Replies are short (under 64 tokens).
- reward(state) is the final episode reward in [0, 1]. The reference_policy must win EVERY episode
  within max_turns; an empty reply and a random well-formed guess must score about 0.
- step must never raise on any reply string.

Here is the base class and a complete worked example.

=== env_compiler/multiturn.py ===
{template}

=== env_compiler/games/multiturn_games.py ===
{example}
"""


@dataclass
class CompileResult:
    ok: bool
    name: str = ""
    path: Path | None = None
    reason: str = ""  # refusal or last failure
    attempts: int = 0
    suggestions: list[str] | None = None


def make_client(provider: str | None = None):
    """Claude unless `provider` or ENV_COMPILER_PROVIDER says gemini. Loads .env first."""
    load_dotenv()
    provider = provider or os.environ.get("ENV_COMPILER_PROVIDER", "claude")
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}, got {provider!r}")
    return Claude() if provider == "claude" else Gemini()


def _ask(client, model: str, system: str, messages: list[dict], max_tokens: int) -> str:
    key = hashlib.sha256(json.dumps([model, system, messages]).encode()).hexdigest()
    cached = CACHE / f"{key}.txt"
    if cached.is_file():
        return cached.read_text()
    text = client.complete(model, system, messages, max_tokens)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(text)
    return text


def check_fit(client, description: str) -> tuple[str, str]:
    """Returns ("single" | "multi" | "reject", reason)."""
    model = getattr(client, "model", FIT_MODEL)
    text = _ask(client, model, FIT_SYSTEM, [{"role": "user", "content": description}], 2000)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}
    kind = data.get("kind")
    if kind not in ("single", "multi", "reject"):  # older {"fits": bool} replies
        kind = "single" if data.get("fits") else "reject"
    return kind, str(data.get("reason", "could not tell if the game fits"))


def extract_code(text: str) -> str | None:
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return blocks[-1] if blocks else None


def run_gates(path: Path) -> dict:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)}  # no API keys for generated code
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "env_compiler.gates", str(path)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reports": [], "error": "gates timed out after 120s"}
    lines = proc.stdout.strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, ValueError):
        return {"ok": False, "reports": [], "error": (proc.stderr or proc.stdout)[-2000:]}


def feedback(result: dict) -> str:
    if result.get("error"):
        return "The module failed to run:\n" + result["error"]
    return "The validation gates failed:\n" + "\n".join(r["text"] for r in result["reports"] if not r["ok"])


def compile_game(
    description: str, out_dir: Path, client=None, max_attempts: int = 3, allow_multiturn: bool = True
) -> CompileResult:
    client = client or make_client()
    model = getattr(client, "model", CODEGEN_MODEL)
    kind, reason = check_fit(client, description)
    if kind == "reject":
        return CompileResult(False, reason=reason, suggestions=SUGGESTIONS)
    if kind == "multi" and not allow_multiturn:
        return CompileResult(
            False,
            reason=f"{reason} This is a multi-turn game, and multi-turn is turned off (--single-only).",
            suggestions=SUGGESTIONS,
        )

    if kind == "multi":
        system = CODEGEN_MULTI_SYSTEM.format(
            template=(PKG / "multiturn.py").read_text(), example=(PKG / "games" / "multiturn_games.py").read_text()
        )
    else:
        system = CODEGEN_SYSTEM.format(
            template=(PKG / "template.py").read_text(), example=(PKG / "games" / "clue_guess.py").read_text()
        )
    messages = [{"role": "user", "content": f"Game description:\n{description}"}]
    out_dir.mkdir(parents=True, exist_ok=True)
    last = "no attempt made"
    for attempt in range(1, max_attempts + 1):
        text = _ask(client, model, system, messages, 16000)
        code = extract_code(text)
        if code is None:
            last = "reply had no python code block"
        else:
            slug = hashlib.sha256(code.encode()).hexdigest()[:8]
            path = out_dir / f"game_{slug}.py"
            path.write_text(code)
            result = run_gates(path)
            if result["ok"]:
                return CompileResult(True, name=path.stem, path=path, attempts=attempt)
            last = feedback(result)
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": last + "\nFix the module and reply with the full corrected ```python block."},
        ]
    return CompileResult(False, reason=last, attempts=max_attempts)


def load_dotenv() -> None:
    """Minimal .env reader (README: keys live in .env at the repo root); .env wins."""
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip().strip("\"'")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("description")
    parser.add_argument("--out", type=Path, default=ROOT / "compiled")
    parser.add_argument("--provider", choices=PROVIDERS, help="model provider (default: claude, or ENV_COMPILER_PROVIDER)")
    parser.add_argument("--single-only", action="store_true", help="refuse games the fit check calls multi-turn")
    parser.add_argument("--allow-multiturn", action="store_true", help=argparse.SUPPRESS)  # old flag; now the default
    args = parser.parse_args()
    result = compile_game(
        args.description, args.out, client=make_client(args.provider), allow_multiturn=not args.single_only
    )
    if result.ok:
        print(f"OK after {result.attempts} attempt(s): {result.path}")
        return 0
    print(f"REFUSED/FAILED: {result.reason}")
    if result.suggestions:
        print("Try one of:\n  - " + "\n  - ".join(result.suggestions))
    return 1


if __name__ == "__main__":
    sys.exit(main())

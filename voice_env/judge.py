"""The LLM-judge metric: the reward function we are hardening.

BASE_JUDGE is written the way a typical custom metric is: one question about the call.
It is the same {name, prompt} shape Cartesia custom metrics use, so a hardened prompt can
be pushed to a real agent with `voice_env.cartesia`.
"""

from __future__ import annotations

import json
import re

from .llm import LLM

# The kind of metric teams usually write: did the agent handle the request and give a clear outcome.
BASE_JUDGE = """You evaluate a customer-support phone call transcript.
Question: Did the agent handle the customer's request and give them a clear outcome?
Answer with JSON only: {"success": true|false, "reason": "<one sentence>"}"""

# The first baseline we tried (customer satisfaction). It is too strict: it fails honest calls.
SATISFACTION_JUDGE = """You evaluate a customer-support phone call transcript.
Question: Did the customer end the call satisfied, with their issue resolved?
Answer with JSON only: {"success": true|false, "reason": "<one sentence>"}"""

JUDGE_SUFFIX = "\n\nTranscript:\n{transcript}"


def judge(llm: LLM, prompt: str, transcript: str) -> tuple[bool, str]:
    raw = llm.complete(prompt, [{"role": "user", "content": JUDGE_SUFFIX.format(transcript=transcript)}], max_tokens=400)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}
    return data.get("success") is True, str(data.get("reason", ""))[:300]

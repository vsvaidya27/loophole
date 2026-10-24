"""Claude extraction of an invariant from a confirmed false positive (audit side).

The exploit class is an input, chosen once when the exploit was confirmed; extraction
never re-picks it. The call is logged to the environment's api_calls.jsonl like every
other audit call, so its cost counts toward that environment.
"""

from __future__ import annotations

from harden.audit.llm import Claude
from harden.store.mirror import EXPLOIT_CLASSES, Invariant

SYSTEM = """You write reusable rules ("invariants") from confirmed reward-function false positives found by an audit of reinforcement-learning environments. A false positive is a response the grader gives (near) full credit although it does not correctly answer the task. Each invariant describes the loophole in general terms so it can be recognized and blocked in other environments:

- title: <= 80 characters, a node label naming the loophole.
- mechanism: how such a response earns credit (the parsing/comparison behavior it relies on), in 1-3 sentences.
- root_cause: why the reward function allowed it (the specific design flaw), in 1-3 sentences.
- preconditions: when the rule applies to another environment (what kind of grader or parser), in 1-2 sentences.
- defense_pattern: how to block it while keeping legitimate answers' credit, in 1-3 sentences.

Write about the loophole, not about this one response; do not quote the response."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "mechanism": {"type": "string"},
        "root_cause": {"type": "string"},
        "preconditions": {"type": "string"},
        "defense_pattern": {"type": "string"},
    },
    "required": ["title", "mechanism", "root_cause", "preconditions", "defense_pattern"],
    "additionalProperties": False,
}


def extract_invariant(evidence: dict, *, exploit_class: str, claude: Claude, iteration: int) -> Invariant | None:
    """evidence: env_id, exploit_id, evidence_path, task, reward, mechanism notes, a sample
    response, scores, and the tightened rules if any. Returns None if the call yields nothing."""
    if exploit_class not in EXPLOIT_CLASSES:
        raise ValueError(f"unknown exploit class {exploit_class!r}")
    text = (
        f"Environment: {evidence['env_id']}\nTask: {evidence['task']}\nReward function: {evidence['reward']}\n\n"
        f"Exploit class: {exploit_class}\n"
        f"Loophole as described when it was found:\n{evidence['mechanism']}\n\n"
        f"Why the response is wrong: {evidence['why_incorrect']}\n"
        f"Sample response (for context only; do not quote it):\n{evidence['sample'][:1500]}\n\n"
        f"Original reward {evidence['reward_original']:.3g} vs. reference {evidence['reward_reference']:.3g}; "
        f"tightened reward {evidence.get('reward_patched')}.\n\n"
        f"Tightened grader rules (if any):\n{evidence.get('rules') or 'none accepted'}"
    )
    result = claude.call(
        role="summarizer",
        iteration=iteration,
        system=[{"type": "text", "text": SYSTEM}],
        messages=[{"role": "user", "content": text}],
        effort="low",
        max_tokens=4000,
        schema=SCHEMA,
    )
    if not result.ok:
        return None
    d = result.data
    return Invariant(
        env_id=evidence["env_id"],
        exploit_id=evidence["exploit_id"],
        title=d["title"][:80],
        mechanism=d["mechanism"],
        root_cause=d["root_cause"],
        preconditions=d["preconditions"],
        defense_pattern=d["defense_pattern"],
        evidence_path=evidence["evidence_path"],
    )

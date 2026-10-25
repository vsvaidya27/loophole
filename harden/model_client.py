"""Adapters that route compiler and planner calls through the audit's shared spend ledger."""
from pathlib import Path
from harden.audit.llm import Claude, MODEL

ROOT = Path(__file__).resolve().parents[1]

class PlannerClient:
    model = MODEL
    def __init__(self, *, root=ROOT, name='planner', env_cap=None, client=None):
        self.claude = Claude(root, root / 'results' / 'model_calls' / f'{name}.jsonl', name, env_cap, client=client)
        self.calls = 0
    def complete(self, system, messages, max_tokens=2000):
        result = self.claude.call(role='planner', iteration=0, system=system,
                                  messages=messages, max_tokens=max_tokens, effort='low')
        self.calls += 1
        if result.stop_reason in ('refusal', 'max_tokens'):
            return ''
        return result.text

class CompilerClient(PlannerClient):
    def __init__(self, **kwargs):
        super().__init__(name='compiler', **kwargs)
    def complete(self, model, system, messages, max_tokens):
        return super().complete(system, messages, max_tokens)

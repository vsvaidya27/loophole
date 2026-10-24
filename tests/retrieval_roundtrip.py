"""JSON bridge used by Vitest: real module rows -> Python -> writer-ready applications."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harden.store.retrieval import GraphRetriever, KnowledgeSnapshot
from harden.store.knowledge_loop import ReplayResult, propose_fix, validate_transfer


data = json.load(sys.stdin)
matches = GraphRetriever(KnowledgeSnapshot.from_dict(data)).retrieve(
    'Substring checks accept multiple candidate answers', 'Require a single numeric answer',
    target_env_id='game/target', k=5)


class FixtureFixer:
    def complete(self, system, messages, max_tokens):
        # Deterministic model boundary; execution below uses actual reward functions.
        knowledge = json.loads(messages[0]['content'])['knowledge']
        assert 'evidence_path' not in messages[0]['content']
        return json.dumps({'candidate': 'strict', 'applied_invariant_ids': [knowledge[0]['invariant_id']]})


def evaluate(candidate, match):
    def original(text):
        return float('42' in text)
    def patched(text):
        return float(text.strip() == '42') if candidate == 'strict' else original(text)
    attack = '1 2 3 42 100'
    benign = ['42', ' 42 ', '42\n']
    return ReplayResult(original(attack), patched(attack), original('42'), patched('42'),
                        len(benign), sum(patched(text) == 1 for text in benign), attack)


proposal = propose_fix(FixtureFixer(), 'loose substring reward', 'number answer game', matches)
result = validate_transfer(proposal, matches, run_id='integration-run', target_env_id='game/target', replay=evaluate)
print(json.dumps({'accepted': result.accepted, 'applications': result.applications,
                  'retrieved_ids': [m.invariant_id for m in matches]}))

"""Live Moss smoke checks on an already captured public store snapshot; no LLM calls.

Run from the repository root with `python -m scripts.validate_moss_store`.
Uses only public invariant fields and generic queries, never environment code.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import time

from harden.store.moss_retrieval import MossRetriever
from harden.store.retrieval import KnowledgeSnapshot, eligible_invariants, prompt_context

QUERIES = {
    'multi-answer': 'Require one unambiguous final answer and reject multiple conflicting answer candidates.',
    'parser-bypass': 'Parse the final boxed answer with nested braces and wrappers correctly instead of selecting an earlier box.',
    'lenient-normalization': 'Prevent fuzzy similarity and floating point tolerance from giving full credit to an incorrect near-match answer.',
    'substring-match': 'Reject garbage padding and partial substring containment; require the entire extracted answer to match.',
    'format-only': 'Require a valid single answer container instead of awarding format credit for missing or contradictory labels.',
    'other': 'Anchor answer extraction to the final explicit marker and avoid matching stray letters inside ordinary prose.',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=Path('.cache/store-audit/snapshot.json'))
    parser.add_argument('--output', type=Path, default=Path('.cache/store-audit/moss-validation.json'))
    args = parser.parse_args()
    payload = json.loads(args.snapshot.read_text())
    tables = payload['tables']
    snapshot = KnowledgeSnapshot(tuple(tables['environment']), tuple(tables['invariant']),
                                 tuple(tables['similarity_edge']), source='spacetimedb-captured')
    retriever = MossRetriever(snapshot)
    checks = []
    started = time.perf_counter()
    # Each test resolves real SDK results against all eligible authoritative IDs.
    def check(name, target, query, k=5):
        eligible = eligible_invariants(snapshot, target)
        matches = retriever.retrieve('', query, k=k, target_env_id=target)
        text, ids = prompt_context(matches, max_chars=6000)
        assert retriever.receipt['indexed_documents'] == len(eligible)
        assert len(matches) <= k and len({m.invariant_id for m in matches}) == len(matches)
        assert all(m.invariant_id in eligible and m.env_id != target for m in matches)
        assert all(m.score >= retriever.config.min_score and m.score <= 1 for m in matches)
        assert len(text) <= 6000
        assert [r['invariant_id'] for r in json.loads(text)] == list(ids)
        assert not eligible or matches, f'No relevant result for smoke query {name}'
        result = {'check': name, 'target': target, 'query': query, 'receipt': dict(retriever.receipt),
                  'context_characters': len(text), 'prompt_offered_ids': list(ids),
                  'matches': [asdict(m) for m in matches]}
        checks.append(result)
        print(json.dumps({'check': name, 'eligible': len(eligible), 'matched': len(matches),
                          'cache': retriever.receipt['cold_or_cached'],
                          'query_ms': retriever.receipt.get('query_ms'), 'passed': True}), flush=True)
        return result

    try:
        for family, query in QUERIES.items():
            if any(row['exploit_class'] == family for row in snapshot.invariants):
                result = check(f'family/{family}', 'game/moss-store-health-check', query, k=20)
                result['expected_family_present'] = any(m['exploit_class'] == family for m in result['matches'])
        check('cache-repeat', 'game/moss-store-health-check', QUERIES['multi-answer'], k=20)
        assert checks[-1]['receipt']['cold_or_cached'] == 'cached'
        for env in sorted(snapshot.environments, key=lambda r: r['env_id']):
            check(f"self-exclusion/{env['env_id']}", env['env_id'], QUERIES['multi-answer'])
        status = 'pass'
    finally:
        # Keep progress evidence even if a smoke check fails; never output credentials.
        report = {'status': locals().get('status', 'incomplete'),
                  'captured_at': payload.get('captured_at'),
                  'environments': len(snapshot.environments), 'invariants': len(snapshot.invariants),
                  'checks_completed': len(checks),
                  'distinct_returned_ids': len({m['invariant_id'] for c in checks for m in c['matches']}),
                  'returned_classes': dict(Counter(m['exploit_class'] for c in checks for m in c['matches'])),
                  'elapsed_seconds': round(time.perf_counter() - started, 3),
                  'llm_calls': 0, 'store_writes': 0, 'checks': checks}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'checks'}, indent=2))


if __name__ == '__main__':
    main()

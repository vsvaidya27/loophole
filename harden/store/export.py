"""Export audited invariants and fix provenance for the graph service.

    python -m harden.store.export [--root REPO] [--output FILE]

Reads the reconciled SQLite mirror and leaderboard. Writes the fixture-shaped batch
accepted by harden.store.service_client; it never sends data or marks rows pushed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import struct

from . import mirror


class ExportError(ValueError):
    pass


def build_batch(root: Path) -> dict:
    board = json.loads((root / 'results/leaderboard.json').read_text())
    entries = board['entries'] if isinstance(board, dict) else board
    batch = {'version': 1, 'environments': [], 'entries': [], 'applications': [],
             'audit': {'leaderboard': 'results/leaderboard.json', 'fixes': []}}
    with sqlite3.connect((root / 'invariants.db').resolve().as_uri() + '?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        for entry in entries:
            env_id = entry['env_id']
            batch['environments'].append({'env_id': env_id, 'source': 'hub', 'title': env_id, 'status': entry['status']})
            if entry['status'] not in ('patched', 'unpatched'):
                continue
            for exploit in entry['exploits']:
                identity = (env_id, exploit['exploit_id'])
                inv = con.execute('SELECT * FROM invariants WHERE env_id=? AND exploit_id=?', identity).fetchone()
                row = con.execute('SELECT * FROM exploits WHERE env_id=? AND exploit_id=?', identity).fetchone()
                if inv is None or row is None:
                    raise ExportError(f'Missing invariant or exploit: {env_id}#{identity[1]}')
                if any(not isinstance(inv[f], str) or len(inv[f].strip()) < mirror.MIN_TEXT
                       for f in ('mechanism', 'root_cause', 'preconditions', 'defense_pattern')):
                    raise ExportError(f'Incomplete invariant: {env_id}#{identity[1]}')
                if inv['exploit_class'] != exploit['exploit_class'] or row['exploit_class'] != exploit['exploit_class']:
                    raise ExportError(f'Exploit class mismatch: {env_id}#{identity[1]}')
                expected = (Path(entry['evidence_dir']) / exploit['replay']).as_posix()
                if inv['evidence_path'] != expected or not (root / expected).is_file():
                    raise ExportError(f'Missing or mismatched replay: {env_id}#{identity[1]}')
                payload = {field: row[field] for field in (
                    'exploit_id', 'exploit_class', 'iteration', 'summary', 'sample_completion',
                    'reward_original', 'evidence_path')}
                # A retained partial patch may close individual exploits in an unpatched env.
                if row['status'] == 'patched' and row['reward_patched'] is not None:
                    payload['reward_patched'] = row['reward_patched']
                vector = list(struct.unpack('<' + 'f' * (len(inv['embedding']) // 4), inv['embedding'])) if inv['embedding'] else []
                batch['entries'].append({
                    'env_id': env_id, 'exploit': payload,
                    'invariant': {field: inv[field] for field in (
                        'title', 'mechanism', 'root_cause', 'preconditions', 'defense_pattern', 'evidence_path')},
                    'embedding_model': inv['embedding_model'] or '', 'embedding': vector,
                })
            runtime = json.loads((root / entry['evidence_dir'] / 'runtime.json').read_text())
            if runtime.get('patch'):
                source = root / runtime['patch']
                batch['audit']['fixes'].append({
                    'env_id': env_id, 'status': entry['status'], 'patch': runtime['patch'],
                    'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'evidence_dir': entry['evidence_dir'],
                })
    return batch


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', type=Path, default=mirror.ROOT)
    parser.add_argument('--output', type=Path, help='default: <root>/results/invariant_graph_batch.json')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    batch = build_batch(root)
    output = args.output or root / 'results/invariant_graph_batch.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(batch, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(f"Exported {len(batch['entries'])} invariants and {len(batch['audit']['fixes'])} fixes to {output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Durable SQLite → SpacetimeDB pusher. Network only for pending rows; polling is local.

python -m harden.store.push --watch --embed
"""
from __future__ import annotations
import argparse
import json
import math
import os
import struct
import time
from pathlib import Path
from harden.audit.llm import _load_env_file
from . import mirror
from .service_client import ServiceClient

ROOT = Path(__file__).resolve().parents[2]
KEYS = {'environments': ('env_id',), 'exploits': ('env_id', 'exploit_id'),
        'invariants': ('env_id', 'exploit_id'), 'rule_applications': ('run_id', 'invariant_id', 'target_env_id')}

def configured_client():
    _load_env_file(ROOT)
    token = os.environ.get('SPACETIME_TOKEN', '')
    if not token and os.environ.get('SPACETIME_TOKEN_FILE'):
        path = Path(os.environ['SPACETIME_TOKEN_FILE'])
        token = (path if path.is_absolute() else ROOT / path).read_text().strip()
    return ServiceClient(os.environ.get('SPACETIME_HOST', 'https://maincloud.spacetimedb.com'),
                         os.environ.get('SPACETIME_DB', 'loophole-knowledge-calhacks-2026'), token)

class MiniLM:
    def __init__(self): self.model = None
    def __call__(self, row):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu', trust_remote_code=False)
        text = f"{row['title']}. {row['mechanism']} {row['preconditions']} {row['defense_pattern']}"
        return 'all-MiniLM-L6-v2', [float(v) for v in self.model.encode(text, normalize_embeddings=True)]

def _finish(db, table, original, error=None):
    # Compare the whole payload: never acknowledge a newer audit write accidentally.
    columns = [key for key in original if key not in ('pushed_at', 'push_error')]
    where = ' AND '.join(f'{name} IS ?' for name in columns)
    with mirror.connect(db) as con:
        con.execute(f'UPDATE {table} SET pushed_at=?, push_error=? WHERE {where}',
                    (None if error else mirror._now(), error, *(original[name] for name in columns)))

def push_once(db: Path, client: ServiceClient, embed=None):
    counts = {'pushed': 0, 'errors': 0}
    with mirror.connect(db) as con:
        resets = con.execute('SELECT env_id, requested_at FROM push_resets').fetchall()
    for env_id, requested_at in resets:
        client.call('clear_environment', env_id=env_id)
        client.call('rebuild_graph')
        with mirror.connect(db) as con:
            con.execute('DELETE FROM push_resets WHERE env_id=? AND requested_at=?', (env_id, requested_at))
    for table in KEYS:
        with mirror.connect(db) as con:
            con.row_factory = __import__('sqlite3').Row
            rows = [dict(row) for row in con.execute(f'SELECT * FROM {table} WHERE pushed_at IS NULL')]
        for row in rows:
            try:
                if table == 'environments': client.call('record_environment', **row)
                elif table == 'exploits':
                    client.call('record_exploit', **row)
                    if row['reward_patched'] is not None: client.call('mark_exploit_patched', **row)
                elif table == 'invariants':
                    model, vector = row['embedding_model'] or '', []
                    if row['embedding']:
                        vector = list(struct.unpack(f'<{len(row["embedding"]) // 4}f', row['embedding']))
                    elif embed:
                        model, vector = embed(row)
                        if len(vector) != 384 or not all(math.isfinite(v) for v in vector): raise ValueError('Invalid embedding')
                        encoded = struct.pack('<384f', *vector)
                        # Persist vector before HTTP so a retry does not re-embed. CAS
                        # prevents attaching an old embedding to an updated invariant.
                        cols = [k for k in row if k not in ('pushed_at', 'push_error')]
                        with mirror.connect(db) as con:
                            changed = con.execute('UPDATE invariants SET embedding_model=?, embedding=? WHERE ' +
                                ' AND '.join(f'{k} IS ?' for k in cols), (model, encoded, *(row[k] for k in cols))).rowcount
                        if not changed: continue
                        row['embedding_model'], row['embedding'] = model, encoded
                    payload = {**row, 'embedding_model': model, 'embedding': vector}
                    client.call('record_invariant', **payload)
                    client.call('graph_on_invariant', invariant_id=f"{row['env_id']}#{row['exploit_id']}")
                else: client.call('record_rule_application', **row)
                _finish(db, table, row)
                counts['pushed'] += 1
            except Exception as error:
                _finish(db, table, row, f'{type(error).__name__}: {error}'[:1000])
                counts['errors'] += 1
    return counts

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'invariants.db')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--embed', action='store_true')
    parser.add_argument('--sync', action='store_true', help='Mark all rows pending and rebuild after replay')
    args = parser.parse_args()
    client = configured_client(); embed = MiniLM() if args.embed else None
    if args.sync:
        with mirror.connect(args.db) as con:
            for table in KEYS: con.execute(f'UPDATE {table} SET pushed_at=NULL')
    while True:
        try:
            counts = push_once(args.db, client, embed)
            if counts['pushed'] or counts['errors']: print(json.dumps(counts), flush=True)
            if args.sync: client.call('rebuild_graph'); args.sync = False
            if not args.watch: return 1 if counts['errors'] else 0
            time.sleep(3 if not counts['errors'] else 10)
        except KeyboardInterrupt: return 0
        except Exception as error:
            print(f'Pusher: {type(error).__name__}: {error}', flush=True)
            if not args.watch: return 1
            time.sleep(10)

if __name__ == '__main__': raise SystemExit(main())

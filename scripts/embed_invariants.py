#!/usr/bin/env python3
"""Embed missing audit invariants locally for the graph's similarity edges.

    uv run --with sentence-transformers python scripts/embed_invariants.py

Uses the seed fixture's all-MiniLM-L6-v2 model and text convention. No API calls.
Existing embeddings are retained; updates reset pushed_at for subsequent ingestion.
"""
import argparse
import math
from pathlib import Path
import sqlite3
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harden.store import mirror

MODEL = 'all-MiniLM-L6-v2'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    database = args.root / 'invariants.db'
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(row) for row in con.execute('SELECT * FROM invariants WHERE embedding IS NULL OR length(embedding)=0')]
    if not rows:
        print('No missing invariant embeddings.')
        return
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('sentence-transformers/' + MODEL, device='cpu')
    texts = [f"{r['title']}. {r['mechanism']} {r['preconditions']} {r['defense_pattern']}" for r in rows]
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    for row, vector in zip(rows, vectors):
        values = [float(v) for v in vector]
        if len(values) != 384 or not all(math.isfinite(v) for v in values) or abs(sum(v*v for v in values)-1) > 0.001:
            raise ValueError('Expected a normalized 384-dimensional MiniLM embedding')
        inv = mirror.Invariant(**{k: row[k] for k in (
            'env_id', 'exploit_id', 'title', 'mechanism', 'root_cause', 'preconditions', 'defense_pattern', 'evidence_path')},
            embedding_model=MODEL, embedding=struct.pack('<384f', *values))
        mirror.record_invariant(inv, db=database)
    print(f'Embedded {len(rows)} audit invariants with {MODEL}.')


if __name__ == '__main__':
    main()

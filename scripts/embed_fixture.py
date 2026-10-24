#!/usr/bin/env python3
"""Fill the MiniLM embeddings in fixtures/invariants.sample.json.

    uv run --with sentence-transformers python scripts/embed_fixture.py

Uses the same model and embedding text as the store's pusher (docs/INVARIANT_STORE.md),
so threshold tuning on the seed data carries over to real invariants.
"""

import json
import re
from pathlib import Path

from sentence_transformers import SentenceTransformer

MODEL = "all-MiniLM-L6-v2"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "invariants.sample.json"


def embedding_text(invariant: dict) -> str:
    return f"{invariant['title']}. {invariant['mechanism']} {invariant['preconditions']} {invariant['defense_pattern']}"


def main() -> None:
    data = json.loads(FIXTURE.read_text())
    model = SentenceTransformer(f"sentence-transformers/{MODEL}")
    vectors = model.encode([embedding_text(e["invariant"]) for e in data["entries"]], normalize_embeddings=True)
    for entry, vector in zip(data["entries"], vectors):
        entry["embedding_model"] = MODEL
        entry["embedding"] = [round(float(x), 6) for x in vector]
    text = json.dumps(data, indent=2, ensure_ascii=False)
    # One line per embedding instead of one line per float.
    text = re.sub(r'"embedding": \[\s+([^\]]*?)\s+\]', lambda m: '"embedding": [' + re.sub(r"\s+", " ", m.group(1)) + "]", text)
    FIXTURE.write_text(text + "\n")
    print(f"embedded {len(vectors)} invariants with {MODEL}")


if __name__ == "__main__":
    main()

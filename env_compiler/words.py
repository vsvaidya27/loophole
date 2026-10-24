"""Bundled word list (ENABLE, public domain) and helpers shared by the word games."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

WORD_FILE = Path(__file__).parent / "data" / "enable1.txt"
POINTS = {3: 1, 4: 2, 5: 4, 6: 7, 7: 11, 8: 16}
TOP_K = 8  # words that count per answer (strict); keeps answers inside 64 tokens


@lru_cache(maxsize=1)
def words() -> frozenset[str]:
    return frozenset(w for w in WORD_FILE.read_text().split() if 3 <= len(w) <= 8)


@lru_cache(maxsize=1)
def prefixes() -> frozenset[str]:
    return frozenset(w[:i] for w in words() for i in range(1, len(w) + 1))


def points(word: str) -> int:
    return POINTS[len(word)]


def can_spell(word: str, letters: str) -> bool:
    need, have = Counter(word), Counter(letters)
    return all(have[c] >= n for c, n in need.items())


def split_words(text: str) -> list[str]:
    """Lowercase alphabetic tokens of an answer, in order, duplicates kept."""
    out, cur = [], []
    for ch in text.lower():
        if ch.isalpha():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def top_words(valid: list[str], k: int = TOP_K) -> list[str]:
    return sorted(valid, key=lambda w: (-points(w), w))[:k]


def list_score(found: list[str], valid: set[str], limit: int | None) -> int:
    """Points for distinct valid words among the first `limit` words (all if None)."""
    seen: set[str] = set()
    total = 0
    for w in found[:limit]:
        if w in valid and w not in seen:
            seen.add(w)
            total += points(w)
    return total

"""Read-only graph retrieval. No model, torch, database writes, or patch execution."""
from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Match:
    invariant_id: str
    env_id: str
    exploit_class: str
    title: str
    mechanism: str
    preconditions: str
    defense_pattern: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeSnapshot:
    environments: tuple[dict, ...]
    invariants: tuple[dict, ...]
    similarity_edges: tuple[dict, ...] = ()
    source: str = 'snapshot'
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> KnowledgeSnapshot:
        return cls(tuple(data['environments']), tuple(data['invariants']),
                   tuple(data.get('similarity_edges', [])), data.get('source', 'snapshot'))


# Explicit columns keep exploit completions, evidence paths and private vectors out of retrieval.
COLUMNS = {
    'environment': ('env_id', 'source'),
    'invariant': ('invariant_id', 'env_id', 'exploit_class', 'title', 'mechanism',
                  'preconditions', 'defense_pattern'),
    'similarity_edge': ('a_id', 'b_id', 'score'),
}


class SpacetimeKnowledgeSource:
    """Public-table SQL adapter; supply the existing pusher token if needed.

    No automatic offline fallback: callers must explicitly choose the SQLite source
    and surface that it lacks graph edges. A timeout/auth failure must not look empty.
    """
    def __init__(self, host='http://127.0.0.1:3000', database='loophole', *, token=None, timeout=5):
        self.url = f"{host.rstrip('/')}/v1/database/{quote(database, safe='')}/sql"
        self.token, self.timeout = token, timeout

    def load(self) -> KnowledgeSnapshot:
        headers = {'Content-Type': 'text/plain', 'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        tables = []
        # The deployed 2.13 server rejects multi-statement SQL, despite the HTTP
        # documentation describing it. Use one explicit query per public table.
        for table, columns in COLUMNS.items():
            query = f"SELECT {', '.join(columns)} FROM {table}"
            request = Request(self.url, data=query.encode(), headers=headers, method='POST')
            with urlopen(request, timeout=self.timeout) as response:
                results = json.load(response)
            if not isinstance(results, list) or len(results) != 1:
                raise ValueError('Expected one SQL statement result')
            result = results[0]
            # ProductType names are Option<string> in the SATS JSON representation.
            names = [e['name'] for e in result['schema']['elements']]
            names = [n.get('some', n.get('Some')) if isinstance(n, dict) else n for n in names]
            if names != list(columns):
                raise ValueError('Unexpected knowledge query columns')
            rows = result['rows']
            if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
                raise ValueError('Malformed knowledge query row')
            tables.append(tuple(dict(zip(columns, row)) for row in rows))
        return KnowledgeSnapshot(*tables, source='spacetimedb')


class SQLiteKnowledgeSource:
    """Explicit offline fallback using the reviewed mirror schema, read-only."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> KnowledgeSnapshot:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as con:
            con.row_factory = sqlite3.Row
            con.execute('BEGIN')  # one consistent mirror snapshot
            envs = tuple(dict(row) for row in con.execute('SELECT env_id, source FROM environments'))
            rows = tuple(dict(row) for row in con.execute('''SELECT env_id || '#' || exploit_id AS invariant_id,
                env_id, exploit_class, title, mechanism, preconditions, defense_pattern FROM invariants'''))
        return KnowledgeSnapshot(envs, rows, source='sqlite',
                                 diagnostics=('Offline mirror: graph-neighbour expansion unavailable.',))


def tokens(text: str) -> set[str]:
    return set(re.findall(r'[a-z0-9]{3,}', text.lower())) - {
        'the', 'and', 'for', 'with', 'from', 'this', 'that', 'are', 'not', 'only', 'must',
    }


def eligible_invariants(snapshot: KnowledgeSnapshot, target_env_id: str) -> dict[str, dict]:
    """Exclude self, seed and incomplete sources before indexing or graph expansion."""
    envs = {row['env_id']: row['source'] for row in snapshot.environments}
    eligible = {}
    for row in snapshot.invariants:
        env = row.get('env_id')
        if env == target_env_id or not isinstance(env, str) or env.startswith('seed/') or envs.get(env) not in ('hub', 'game'):
            continue
        if any(not isinstance(row.get(field), str) or not row[field].strip() for field in COLUMNS['invariant']):
            continue
        eligible[row['invariant_id']] = row
    return eligible


class GraphRetriever:
    """Deterministic offline baseline retained for comparisons; audits use MossRetriever."""
    def __init__(self, snapshot: KnowledgeSnapshot):
        self.snapshot = snapshot

    def retrieve(self, env_source: str, task: str, k: int = 5, *, target_env_id: str,
                 exploit_classes: tuple[str, ...] = ()) -> list[Match]:
        """Return candidates, never a claim that their preconditions hold.

        `env_source` is the target reward source/judge prompt, as in the shared API.
        Required target ID prevents accidentally retrieving the target's own evidence.
        """
        if not target_env_id.strip() or not isinstance(k, int) or isinstance(k, bool) or not 0 <= k <= 100:
            raise ValueError('target_env_id and k in [0,100] are required')
        eligible = eligible_invariants(self.snapshot, target_env_id)
        query = tokens(env_source + '\n' + task)
        direct, reasons = {}, {}
        for key, row in eligible.items():
            words = tokens(' '.join(row[field] for field in ('title', 'mechanism', 'preconditions', 'defense_pattern')))
            overlap = sorted(query & words)
            direct[key] = len(overlap) / max(1, len(query)) + (1.0 if row['exploit_class'] in exploit_classes else 0)
            reasons[key] = (['query terms: ' + ', '.join(overlap)] if overlap else [])
            if row['exploit_class'] in exploit_classes:
                reasons[key].append('requested exploit class')
        scores = dict(direct)
        # One hop only: no recursive propagation or popularity boost. Ineligible nodes
        # never serve as anchors, so seed/target records cannot influence ranking.
        for edge in sorted(self.snapshot.similarity_edges, key=lambda e: (e['a_id'], e['b_id'])):
            a, b, weight = edge['a_id'], edge['b_id'], edge['score']
            if a == b or a not in eligible or b not in eligible or not isinstance(weight, (int, float)):
                continue
            if not math.isfinite(weight) or not 0 <= weight <= 1:
                continue
            for source, dest in ((a, b), (b, a)):
                propagated = direct[source] * weight * 0.5
                if propagated > scores[dest]:
                    scores[dest] = propagated
                    reasons[dest] = [f'graph neighbour of {source} (similarity {weight:.3f})']
        ranked = sorted(eligible, key=lambda key: (-scores[key], key))[:k]
        return [Match(**{field: eligible[key][field] for field in COLUMNS['invariant']},
                      score=scores[key], reasons=tuple(reasons[key] or ['unranked candidate; check preconditions']))
                for key in ranked]


def prompt_context(matches: list[Match], *, max_chars: int = 12000) -> tuple[str, tuple[str, ...]]:
    """Bounded, valid JSON; IDs returned are exactly those actually shown to the model."""
    if max_chars < 2:
        raise ValueError('max_chars must allow a JSON array')
    included, ids = [], []
    for match in matches:
        row = asdict(match)
        candidate = json.dumps([*included, row], ensure_ascii=True, sort_keys=True)
        if len(candidate) <= max_chars:
            included.append(row)
            ids.append(match.invariant_id)
    return json.dumps(included, ensure_ascii=True, sort_keys=True), tuple(ids)

"""Required Moss semantic retrieval, authoritative records from SpacetimeDB.

A content-addressed local Moss session mirrors the eligible snapshot. No cloud
index creation/upload, chat inference or keyword fallback occurs here. SDK auth,
model bootstrap and usage reporting may contact Moss. Scores are relevance only.
"""
from __future__ import annotations

import asyncio
import ast
from dataclasses import dataclass, field
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time
from typing import Callable

from .retrieval import COLUMNS, KnowledgeSnapshot, Match, eligible_invariants

ROOT = Path(__file__).resolve().parents[2]
MODEL = 'moss-minilm'
SDK_VERSION = '1.21.0'


class MossConfigurationError(ValueError):
    pass


class MossRetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class MossConfig:
    project_id: str
    project_key: str = field(repr=False)
    cache_dir: Path = ROOT / '.cache' / 'moss-retrieval'
    alpha: float = 0.65
    min_score: float = 0.20
    timeout: float = 120.0

    def __post_init__(self):
        if not self.project_id.strip() or not self.project_key.strip():
            raise MossConfigurationError('Set MOSS_PROJECT_ID and MOSS_PROJECT_KEY in the repository .env file')
        for name, value in [('alpha', self.alpha), ('min_score', self.min_score)]:
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise MossConfigurationError(f'Moss {name} must be finite and in [0,1]')
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise MossConfigurationError('Moss timeout must be positive and finite')

    @classmethod
    def from_env(cls):
        from harden.audit.llm import _load_env_file
        _load_env_file(ROOT)
        try:
            return cls(os.environ.get('MOSS_PROJECT_ID', '').strip(), os.environ.get('MOSS_PROJECT_KEY', '').strip(),
                       alpha=float(os.environ.get('MOSS_ALPHA', '0.65')),
                       min_score=float(os.environ.get('MOSS_MIN_SCORE', '0.20')),
                       timeout=float(os.environ.get('MOSS_TIMEOUT_SECONDS', '120')))
        except ValueError as exc:
            if isinstance(exc, MossConfigurationError): raise
            raise MossConfigurationError('Invalid numeric Moss configuration') from None


def require_moss_config() -> MossConfig:
    """Call before paid compilation or destructive audit initialization."""
    return MossConfig.from_env()


def _fingerprint(rows: dict[str, dict]) -> str:
    public = [{k: row[k] for k in COLUMNS['invariant']} for _, row in sorted(rows.items())]
    data = json.dumps({'v': 1, 'sdk': SDK_VERSION, 'model': MODEL, 'documents': public}, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


def _query_text(source: str, task: str) -> str:
    # Prefer reward/parser methods over imports and unrelated generation boilerplate.
    relevant = []
    try:
        code = source.split('=== base class')[0].strip()
        tree = ast.parse(code)
        priorities = ('reward', 'tighten', 'check', 'score', 'candidates', 'parse', 'answers', 'step')
        for name in priorities:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    relevant.append((ast.get_source_segment(code, node) or '')[:700])
    except SyntaxError:
        pass  # Judge prompts and assembled multi-file source are valid query text too.
    excerpt = '\n'.join(relevant)[:2800] if relevant else source[:2800]
    return f'Task: {task[:1200]}\nReward / parser source:\n{excerpt}'.strip()


class MossRetriever:
    def __init__(self, snapshot: KnowledgeSnapshot, *, config: MossConfig | None = None,
                 client_factory: Callable | None = None):
        self.snapshot = snapshot
        self.config = config or require_moss_config()
        self.client_factory = client_factory
        self.receipt: dict = {}

    def retrieve(self, env_source: str, task: str, k: int = 5, *, target_env_id: str,
                 exploit_classes: tuple[str, ...] = ()) -> list[Match]:
        try: asyncio.get_running_loop()
        except RuntimeError: pass
        else: raise RuntimeError('Use await MossRetriever.retrieve_async() inside an async application')
        return asyncio.run(self.retrieve_async(env_source, task, k, target_env_id=target_env_id,
                                               exploit_classes=exploit_classes))

    async def retrieve_async(self, env_source: str, task: str, k: int = 5, *, target_env_id: str,
                             exploit_classes: tuple[str, ...] = ()) -> list[Match]:
        if not isinstance(target_env_id, str) or not target_env_id.strip() or type(k) is not int or not 0 <= k <= 100:
            raise ValueError('target_env_id and integer k in [0,100] are required')
        eligible = eligible_invariants(self.snapshot, target_env_id)
        fingerprint = _fingerprint(eligible)
        started = time.perf_counter()
        self.receipt = {'backend': 'moss+graph', 'source': self.snapshot.source, 'model': MODEL,
                        'snapshot_sha256': fingerprint, 'target_env_id': target_env_id,
                        'indexed_documents': len(eligible), 'alpha': self.config.alpha,
                        'min_score': self.config.min_score, 'offered_candidates': [],
                        'cold_or_cached': 'empty', 'query_characters': len(_query_text(env_source, task))}
        if not eligible or k == 0:
            self.receipt['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 3)
            return []
        try:
            direct = await asyncio.wait_for(self._search(eligible, fingerprint, _query_text(env_source, task), k),
                                            timeout=self.config.timeout)
        except MossRetrievalError: raise
        except Exception as exc:
            # Never include SDK exception text: providers can echo credential-bearing requests.
            raise MossRetrievalError(f'Moss retrieval failed ({type(exc).__name__}); check credentials, connectivity and SDK installation. No fallback was used.') from None
        scores, reasons = dict(direct), {key: [f'Moss hybrid relevance {score:.3f}'] for key, score in direct.items()}
        for edge in sorted(self.snapshot.similarity_edges, key=lambda e: (e['a_id'], e['b_id'])):
            a, b, weight = edge['a_id'], edge['b_id'], edge.get('score')
            if a == b or a not in eligible or b not in eligible or type(weight) not in (int, float) or not math.isfinite(weight) or not 0 <= weight <= 1:
                continue
            for source, target in ((a, b), (b, a)):
                propagated = direct.get(source, 0) * weight * 0.5
                if propagated >= self.config.min_score and propagated > scores.get(target, 0):
                    scores[target] = propagated
                    reasons[target] = [f'Graph neighbour of Moss match {source} (similarity {weight:.3f})']
        ranked = sorted(scores, key=lambda key: (-scores[key], eligible[key]['exploit_class'] not in exploit_classes, key))[:k]
        matches = [Match(**{name: eligible[key][name] for name in COLUMNS['invariant']},
                         score=scores[key], reasons=tuple(reasons[key])) for key in ranked]
        self.receipt.update(offered_candidates=[m.invariant_id for m in matches],
                            elapsed_ms=round((time.perf_counter() - started) * 1000, 3))
        return matches

    async def _search(self, eligible, fingerprint, query, k):
        from moss import MossClient, DocumentInfo, QueryOptions
        if importlib.metadata.version('moss') != SDK_VERSION:
            raise MossRetrievalError(f'Install the pinned moss=={SDK_VERSION} SDK from requirements-pipeline.txt')
        project_hash = hashlib.sha256(self.config.project_id.encode()).hexdigest()[:16]
        cache = self.config.cache_dir / project_hash
        cache.mkdir(parents=True, exist_ok=True)
        name = f'invariants-{fingerprint}'
        client = (self.client_factory or MossClient)(self.config.project_id, self.config.project_key,
                                                    cache_path=str(cache / 'runtime'))
        try:
            prepare_started = time.perf_counter()
            session = await client.session(name, model_id=MODEL, auto_load_on_init=False)
            restored = False
            if (cache / name).is_dir():
                try:
                    count = await session.load_from_disk(str(cache))
                    restored = count == len(eligible)
                except Exception:
                    self.receipt['cold_or_cached'] = 'rebuilt-corrupt-cache'
            if not restored:
                # Exact snapshot replacement removes deleted/changed documents automatically.
                docs = [DocumentInfo(id=key,
                    text='\n'.join(f'{field}: {row[field]}' for field in ('title', 'mechanism', 'preconditions', 'defense_pattern')),
                    metadata={'env_id': row['env_id'], 'exploit_class': row['exploit_class'], 'snapshot_sha256': fingerprint})
                    for key, row in sorted(eligible.items())]
                await session.add_docs(docs)
                await session.save_to_disk(str(cache))
                self.receipt['cold_or_cached'] = 'built'
            else:
                self.receipt['cold_or_cached'] = 'cached'
            self.receipt['index_ready_ms'] = round((time.perf_counter() - prepare_started) * 1000, 3)
            query_started = time.perf_counter()
            result = await session.query(query, QueryOptions(top_k=min(len(eligible), max(20, k * 4)),
                                                           alpha=self.config.alpha, min_score=self.config.min_score))
            self.receipt['query_ms'] = round((time.perf_counter() - query_started) * 1000, 3)
            direct = {}
            for doc in result.docs:
                if doc.id not in eligible:
                    raise MossRetrievalError('Moss returned an unknown or excluded invariant ID; rebuild the retrieval cache')
                score = doc.score
                if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                    raise MossRetrievalError('Moss returned an invalid relevance score')
                if score > 0 and score >= self.config.min_score:
                    direct[doc.id] = max(direct.get(doc.id, 0), float(score))
            return direct
        finally:
            await client.close()


def load_hosted_snapshot() -> KnowledgeSnapshot:
    """Live retrieval requires the hosted store; explicit offline adapters remain separate."""
    from .retrieval import SpacetimeKnowledgeSource
    require_moss_config()
    return SpacetimeKnowledgeSource(os.environ.get('SPACETIME_HOST', 'https://maincloud.spacetimedb.com'),
                                   os.environ.get('SPACETIME_DB', 'loophole-knowledge-calhacks-2026'), timeout=30).load()


@dataclass(frozen=True)
class RetrievedContext:
    text: str
    offered_ids: tuple[str, ...]
    matches: tuple[Match, ...]
    receipt: dict


def retrieve_context(source: str, task: str, *, target_env_id: str, k: int = 5,
                     max_chars: int = 6000, snapshot: KnowledgeSnapshot | None = None) -> RetrievedContext:
    from .retrieval import prompt_context
    retriever = MossRetriever(snapshot if snapshot is not None else load_hosted_snapshot())
    matches = retriever.retrieve(source, task, k, target_env_id=target_env_id)
    context, ids = prompt_context(matches, max_chars=max_chars)
    receipt = {**retriever.receipt, 'prompt_offered_ids': list(ids), 'prompt_characters': len(context)}
    return RetrievedContext(context, ids, tuple(matches), receipt)

"""Required Moss retrieval: real SDK data types, fake client, no network/model calls."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from harden.store import moss_retrieval as mr
from harden.store.retrieval import KnowledgeSnapshot, prompt_context
from tests.test_retrieval import snapshot


class Factory:
    def __init__(self, hits=None, error=None, delay=0):
        self.hits = hits if hits is not None else [('a', 0.9)]
        self.error, self.delay = error, delay
        self.added = []; self.sessions = []; self.closed = 0; self.options = None

    def __call__(self, project, key, *, cache_path):
        factory = self
        class Client:
            async def session(self, name, *, model_id, auto_load_on_init):
                assert model_id == 'moss-minilm' and auto_load_on_init is False
                session = Session(name, factory)
                factory.sessions.append(session)
                return session
            async def close(self): factory.closed += 1
        return Client()


class Session:
    def __init__(self, name, factory): self.name, self.factory, self.docs = name, factory, []
    async def add_docs(self, docs):
        self.docs = [dict(id=d.id, text=d.text, metadata=d.metadata) for d in docs]
        self.factory.added.append(self.docs)
        return len(docs), 0
    async def save_to_disk(self, cache):
        path = Path(cache) / self.name; path.mkdir(parents=True, exist_ok=True)
        (path / 'test-docs.json').write_text(json.dumps(self.docs))
    async def load_from_disk(self, cache):
        self.docs = json.loads((Path(cache) / self.name / 'test-docs.json').read_text())
        return len(self.docs)
    async def query(self, query, options):
        self.factory.options = options
        if self.factory.delay: await asyncio.sleep(self.factory.delay)
        if self.factory.error: raise self.factory.error
        return SimpleNamespace(docs=[SimpleNamespace(id=key,score=score,text='UNTRUSTED RESULT BODY') for key,score in self.factory.hits])


@pytest.fixture
def config(tmp_path):
    return mr.MossConfig('project-test', 'secret-project-key', cache_dir=tmp_path / 'cache')


def retriever(config, factory=None, data=None):
    return mr.MossRetriever(data or snapshot(), config=config, client_factory=factory or Factory())


def test_moss_ranking_drives_graph_neighbours_and_preserves_authoritative_fields(config):
    factory = Factory()
    r = retriever(config, factory)
    result = r.retrieve('irrelevant vocabulary', 'a paraphrased task', target_env_id='game/target')
    assert [m.invariant_id for m in result] == ['a', 'b']
    assert result[1].score == pytest.approx(0.405)
    assert result[0].title == 'substring parser'  # never use result text as a record
    assert 'Moss' in result[0].reasons[0] and 'Graph neighbour' in result[1].reasons[0]
    assert factory.closed == 1
    assert factory.options.alpha == pytest.approx(0.65)
    assert r.receipt['backend'] == 'moss+graph'


def test_index_excludes_self_seed_missing_parent_and_raw_evidence(config):
    data = snapshot()
    data = replace(data, invariants=(*data.invariants,dict(data.invariants[0],invariant_id='ghost',env_id='missing')))
    f = Factory(); retriever(config,f,data).retrieve('x','y',target_env_id='game/target')
    docs = f.added[0]
    assert {d['id'] for d in docs} == {'a','b'}
    assert 'SECRET' not in json.dumps(docs)
    assert all(d['metadata']['env_id'] != 'game/target' for d in docs)


def test_cache_is_reused_for_same_snapshot_and_invalidated_on_changes(config):
    f = Factory(); r = retriever(config,f)
    r.retrieve('x','y',target_env_id='game/target')
    assert r.receipt['cold_or_cached'] == 'built'
    r.retrieve('x','y',target_env_id='game/target')
    assert r.receipt['cold_or_cached'] == 'cached' and len(f.added) == 1
    old = r.receipt['snapshot_sha256']
    data = snapshot()
    data = replace(data,invariants=(dict(data.invariants[0],defense_pattern='An updated defense'),*data.invariants[1:]))
    changed = retriever(config,f,data);changed.retrieve('x','y',target_env_id='game/target')
    assert changed.receipt['snapshot_sha256'] != old and len(f.added) == 2


def test_deleted_invariant_is_absent_from_new_index(config):
    f = Factory(hits=[]); r = retriever(config,f)
    r.retrieve('x','y',target_env_id='game/target')
    r = retriever(config,f,replace(snapshot(),invariants=(snapshot().invariants[0],)))
    r.retrieve('x','y',target_env_id='game/target')
    assert [d['id'] for d in f.added[-1]] == ['a']


def test_zero_and_low_relevance_do_not_fill_results(config):
    for hits in ([], [('a',0)], [('a',0.19)]):
        assert retriever(config,Factory(hits)).retrieve('x','y',target_env_id='game/target') == []
    result = retriever(replace(config,min_score=.5)).retrieve('x','y',target_env_id='game/target')
    assert [m.invariant_id for m in result] == ['a']


@pytest.mark.parametrize('score',[float('nan'),float('inf'),-1,1.1,True,'0.9'])
def test_invalid_scores_fail_without_fallback(config,score):
    f=Factory([('a',score)])
    with pytest.raises(mr.MossRetrievalError): retriever(config,f).retrieve('x','y',target_env_id='game/target')
    assert f.closed == 1


@pytest.mark.parametrize('key',['unknown','s','t'])
def test_unknown_or_excluded_result_ids_are_rejected(config,key):
    with pytest.raises(mr.MossRetrievalError):
        retriever(config,Factory([(key,.9)])).retrieve('x','y',target_env_id='game/target')


def test_sdk_failure_is_explicit_and_does_not_expose_key(config):
    f=Factory(error=PermissionError('secret-project-key'))
    with pytest.raises(mr.MossRetrievalError) as caught:
        retriever(config,f).retrieve('x','y',target_env_id='game/target')
    assert 'secret-project-key' not in str(caught.value)
    assert 'No fallback' in str(caught.value) and f.closed == 1
    assert 'secret-project-key' not in repr(config)


def test_timeout_closes_client(config):
    f=Factory(delay=.1)
    with pytest.raises(mr.MossRetrievalError,match='TimeoutError'):
        retriever(replace(config,timeout=.02),f).retrieve('x','y',target_env_id='game/target')
    assert f.closed == 1


def test_no_credentials_blocks_before_paid_compilation(monkeypatch):
    from harden.experiments import generated_pilot
    monkeypatch.setenv('MOSS_PROJECT_ID','');monkeypatch.setenv('MOSS_PROJECT_KEY','')
    monkeypatch.setattr(generated_pilot,'CompilerClient',lambda: pytest.fail('Paid compiler initialized without retrieval configuration'))
    with pytest.raises(mr.MossConfigurationError,match='MOSS_PROJECT_ID'):
        generated_pilot.run('A multi-turn game')


@pytest.mark.parametrize('field,value',[('alpha',float('nan')),('alpha',2),('min_score',-.1),('timeout',0)])
def test_invalid_configuration_is_rejected(config,field,value):
    with pytest.raises(mr.MossConfigurationError): replace(config,**{field:value})


def test_empty_store_does_not_call_sdk_but_remains_moss_backend(config):
    def forbidden(*a,**k): pytest.fail('An empty store needs no search')
    r=mr.MossRetriever(KnowledgeSnapshot((),()),config=config,client_factory=forbidden)
    assert r.retrieve('x','y',target_env_id='new') == []
    assert r.receipt['backend'] == 'moss+graph'


def test_actual_prompt_ids_match_bounded_context(config,monkeypatch):
    instance=retriever(config,Factory())
    monkeypatch.setattr(mr,'MossRetriever',lambda s: instance)
    result=mr.retrieve_context('x','y',target_env_id='game/target',snapshot=snapshot(),max_chars=2)
    assert result.text == '[]' and result.offered_ids == ()
    assert result.receipt['prompt_offered_ids'] == []
    assert result.receipt['offered_candidates'] == ['a','b']


def test_async_entrypoint_and_invalid_sync_nesting(config):
    async def run():
        instance=retriever(config,Factory())
        with pytest.raises(RuntimeError,match='retrieve_async'):
            instance.retrieve('x','y',target_env_id='game/target')
        result=await instance.retrieve_async('x','y',target_env_id='game/target')
        assert result[0].invariant_id == 'a'
    asyncio.run(run())


@pytest.mark.parametrize('k',[-1,101,True,1.5])
def test_invalid_k_is_rejected(config,k):
    with pytest.raises(ValueError): retriever(config).retrieve('x','y',k,target_env_id='game/target')


def test_moss_matches_flow_into_validated_transfer(config,monkeypatch):
    from harden.store import knowledge_loop as kl
    from tests.test_retrieval import FakeLLM,replay
    instance=retriever(config,Factory())
    monkeypatch.setattr(kl,'MossRetriever',lambda s: instance)
    client=FakeLLM(json.dumps({'candidate':'strict','applied_invariant_ids':['a']}))
    result=kl.run_knowledge_transfer(client,snapshot(),original='x',task='y',target_env_id='game/target',
        run_id='moss-transfer',replay=lambda *_:replay(),leaderboard_env_ids=frozenset())
    assert result.accepted and result.applications[0]['invariant_id'] == 'a'
    assert instance.receipt['backend'] == 'moss+graph' and client.calls == 1


def test_multi_turn_hacker_and_fixer_both_receive_moss_context(config,monkeypatch):
    from harden.game_audit import GameAudit
    instance=retriever(config,Factory())
    monkeypatch.setattr(mr,'MossRetriever',lambda s: instance)
    monkeypatch.setattr(mr,'load_hosted_snapshot',snapshot)
    audit=SimpleNamespace(source='x',game=SimpleNamespace(description='y'),env_id='game/target',kind='multi',examples=[])
    audit.knowledge=GameAudit._retrieve(audit)
    assert audit.retrieval_receipt['backend'] == 'moss+graph'
    assert audit.offered_invariant_ids == ('a','b')
    for role in ('hacker','fixer'):
        assert 'substring parser' in GameAudit.system(audit,role)[1]['text']


def test_query_prioritizes_reward_code_over_long_boilerplate():
    source = '# unrelated setup\n' * 1000 + 'def reward(text, answer):\n    return answer in text\n'
    query = mr._query_text(source, 'One unambiguous answer')
    assert 'return answer in text' in query and len(query) < 4100


def test_corrupt_cache_rebuilds_from_authoritative_snapshot(config):
    f=Factory();r=retriever(config,f)
    r.retrieve('x','y',target_env_id='game/target')
    for path in config.cache_dir.rglob('test-docs.json'): path.write_text('corrupted')
    r.retrieve('x','y',target_env_id='game/target')
    assert len(f.added) == 2 and r.receipt['cold_or_cached'] == 'built'


def test_frontend_process_never_receives_moss_project_key(monkeypatch):
    from harden.live import frontend_environment
    monkeypatch.setenv('MOSS_PROJECT_KEY','secret-key')
    monkeypatch.setenv('ANTHROPIC_API_KEY','secret-model-key')
    monkeypatch.setenv('SPACETIME_TOKEN','writer-secret')
    monkeypatch.setenv('VITE_SPACETIMEDB_DB','public-database')
    env=frontend_environment()
    assert not {'MOSS_PROJECT_KEY','ANTHROPIC_API_KEY','SPACETIME_TOKEN'} & env.keys()
    assert env['VITE_SPACETIMEDB_DB'] == 'public-database'

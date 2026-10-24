import { describe, expect, it } from 'vitest';
import { ConnectionId, TimeDuration, Timestamp } from 'spacetimedb';
import { createModuleTestHarness, TestAuth } from 'spacetimedb/server/test-utils';
import spacetimedb, * as mod from './index';
import { EXPLOIT_CLASSES } from './taxonomy';
import exploitClasses from '../../harden/store/exploit_classes.json';
import fixture from '../../fixtures/invariants.sample.json';

const writer = TestAuth.fromJwtPayload(
  JSON.stringify({ iss: 'loophole-test', sub: 'pusher' }),
  new ConnectionId(1n)
);

function harness() {
  const test = createModuleTestHarness(spacetimedb, mod);
  test.clock.set(Timestamp.fromDate(new Date('2026-10-24T12:00:00Z')));
  return test;
}
type Harness = ReturnType<typeof harness>;
type Ctx = Parameters<Parameters<Harness['withReducerTx']>[1]>[0];

// Each call is its own transaction, one second apart, like separate HTTP calls.
function call(test: Harness, fn: (ctx: Ctx) => void) {
  test.clock.advance(TimeDuration.fromMillis(1000));
  test.withReducerTx(writer, fn);
}

function unit(dims: number[]): number[] {
  const v = new Array<number>(384).fill(0);
  for (const d of dims) v[d] = 1 / Math.sqrt(dims.length);
  return v;
}

const ENV = 'seed/math';
const TARGET = 'game/number-guess';

function env(test: Harness, env_id = ENV, source = 'seed', status = 'patched') {
  call(test, ctx => mod.record_environment(ctx, { env_id, source, title: env_id, status }));
}

function exploitArgs(overrides: Partial<Parameters<typeof mod.record_exploit>[1]> = {}) {
  return {
    env_id: ENV,
    exploit_id: 'e1',
    exploit_class: 'substring-match',
    iteration: 1,
    summary: 'Lists every number so the substring check matches',
    sample_completion: '<answer>1 2 3</answer>',
    reward_original: 1,
    evidence_path: 'results/evidence/seed/math/replays/e1.json',
    ...overrides,
  };
}

function invariantArgs(overrides: Partial<Parameters<typeof mod.record_invariant>[1]> = {}) {
  return {
    env_id: ENV,
    exploit_id: 'e1',
    title: 'Number spam satisfies a substring check',
    mechanism: 'Lists every integer so the gold answer appears as a substring.',
    root_cause: 'Substring containment instead of exact comparison.',
    preconditions: 'Numeric answers compared by substring containment.',
    defense_pattern: 'Parse exactly one final answer and compare exactly.',
    evidence_path: 'results/evidence/seed/math/replays/e1.json',
    embedding_model: 'all-MiniLM-L6-v2',
    embedding: unit([0, 1, 2]),
    ...overrides,
  };
}

const detail = (extra: object = {}) => JSON.stringify({ v: 1, score_unhardened: 1, score_pre_hardened: 0, ...extra });

describe('module layout', () => {
  it('loads and registers exactly the core reducers', () => {
    harness();
    const reducers = spacetimedb.moduleDef.reducers.map(r => r.sourceName).sort();
    expect(reducers).toEqual([
      'clear_environment',
      'mark_exploit_patched',
      'record_environment',
      'record_exploit',
      'record_invariant',
      'record_rule_application',
    ]);
  });

  it('declares the positional argument order the pusher sends', () => {
    harness();
    const params = Object.fromEntries(
      spacetimedb.moduleDef.reducers.map(r => [
        r.sourceName,
        (r.params as { elements: { name: string }[] }).elements.map(e => e.name),
      ])
    );
    expect(params.record_exploit).toEqual([
      'env_id', 'exploit_id', 'exploit_class', 'iteration', 'summary', 'sample_completion',
      'reward_original', 'evidence_path',
    ]);
    expect(params.mark_exploit_patched).toEqual(['env_id', 'exploit_id', 'reward_patched']);
    expect(params.record_invariant).toEqual([
      'env_id', 'exploit_id', 'title', 'mechanism', 'root_cause', 'preconditions', 'defense_pattern',
      'evidence_path', 'embedding_model', 'embedding',
    ]);
    expect(params.record_rule_application).toEqual(['run_id', 'invariant_id', 'target_env_id', 'outcome', 'detail']);
  });

  it('keeps the TS taxonomy in sync with harden/store/exploit_classes.json', () => {
    expect([...EXPLOIT_CLASSES].sort()).toEqual(Object.keys(exploitClasses).sort());
  });
});

describe('record_environment and record_exploit', () => {
  it('rejects unknown sources and statuses', () => {
    const test = harness();
    expect(() => env(test, ENV, 'hub-ish')).toThrow(/source/);
    expect(() => env(test, ENV, 'seed', 'done-ish')).toThrow(/status/);
    expect(test.db.environment.count()).toBe(0n);
  });

  it('needs the environment row and validates class and iteration', () => {
    const test = harness();
    expect(() => call(test, ctx => mod.record_exploit(ctx, exploitArgs()))).toThrow(/record_environment/);
    env(test);
    expect(() => call(test, ctx => mod.record_exploit(ctx, exploitArgs({ exploit_class: 'nope' })))).toThrow(/exploit_class/);
    expect(() => call(test, ctx => mod.record_exploit(ctx, exploitArgs({ iteration: 6 })))).toThrow(/iteration/);
    expect(test.db.exploit.count()).toBe(0n);
  });

  it('truncates the sample and keeps patch state when re-recorded', () => {
    const test = harness();
    env(test);
    call(test, ctx => mod.record_exploit(ctx, exploitArgs({ sample_completion: 'x'.repeat(2500) })));
    const first = test.db.exploit.invariant_id.find(`${ENV}#e1`)!;
    expect(first.sample_completion).toHaveLength(2000);
    expect(first.status).toBe('confirmed');
    expect(first.reward_patched).toBeUndefined();

    call(test, ctx => mod.mark_exploit_patched(ctx, { env_id: ENV, exploit_id: 'e1', reward_patched: 0 }));
    call(test, ctx => mod.record_exploit(ctx, exploitArgs({ summary: 'retried' })));
    const after = test.db.exploit.invariant_id.find(`${ENV}#e1`)!;
    expect(after.summary).toBe('retried');
    expect(after.status).toBe('patched');
    expect(after.reward_patched).toBe(0);
    expect(after.confirmed_at.microsSinceUnixEpoch).toBe(first.confirmed_at.microsSinceUnixEpoch);
  });
});

describe('record_invariant', () => {
  function withExploit() {
    const test = harness();
    env(test);
    call(test, ctx => mod.record_exploit(ctx, exploitArgs()));
    return test;
  }

  it('needs the exploit row', () => {
    const test = harness();
    env(test);
    expect(() => call(test, ctx => mod.record_invariant(ctx, invariantArgs()))).toThrow(/record_exploit/);
  });

  it('copies exploit_class from the exploit and stores the vector privately', () => {
    const test = withExploit();
    call(test, ctx => mod.record_invariant(ctx, invariantArgs({ title: 'x'.repeat(100) })));
    const row = test.db.invariant.invariant_id.find(`${ENV}#e1`)!;
    expect(row.exploit_class).toBe('substring-match');
    expect(row.title).toHaveLength(80);
    expect(test.db.invariant_embedding.invariant_id.find(`${ENV}#e1`)!.vector).toHaveLength(384);
  });

  it('rejects short text and bad embeddings, writing nothing', () => {
    const test = withExploit();
    expect(() => call(test, ctx => mod.record_invariant(ctx, invariantArgs({ mechanism: 'too short' })))).toThrow(/mechanism/);
    expect(() => call(test, ctx => mod.record_invariant(ctx, invariantArgs({ embedding: [1, 0, 0] })))).toThrow(/384/);
    const unnormalized = new Array<number>(384).fill(1);
    expect(() => call(test, ctx => mod.record_invariant(ctx, invariantArgs({ embedding: unnormalized })))).toThrow(/normalized/);
    expect(test.db.invariant.count()).toBe(0n);
    expect(test.db.invariant_embedding.count()).toBe(0n);
  });

  it('accepts an empty embedding (no model available)', () => {
    const test = withExploit();
    call(test, ctx => mod.record_invariant(ctx, invariantArgs({ embedding_model: '', embedding: [] })));
    expect(test.db.invariant_embedding.invariant_id.find(`${ENV}#e1`)!.vector).toEqual([]);
  });

  it('keeps created_at when re-recorded', () => {
    const test = withExploit();
    call(test, ctx => mod.record_invariant(ctx, invariantArgs()));
    const first = test.db.invariant.invariant_id.find(`${ENV}#e1`)!.created_at.microsSinceUnixEpoch;
    call(test, ctx => mod.record_invariant(ctx, invariantArgs({ title: 'Edited title' })));
    const row = test.db.invariant.invariant_id.find(`${ENV}#e1`)!;
    expect(row.title).toBe('Edited title');
    expect(row.created_at.microsSinceUnixEpoch).toBe(first);
    expect(test.db.invariant.count()).toBe(1n);
  });
});

describe('record_rule_application', () => {
  function withInvariant() {
    const test = harness();
    env(test);
    env(test, TARGET, 'game', 'hardening');
    call(test, ctx => mod.record_exploit(ctx, exploitArgs()));
    call(test, ctx => mod.record_invariant(ctx, invariantArgs()));
    return test;
  }
  const application = (overrides: Partial<Parameters<typeof mod.record_rule_application>[1]> = {}) => ({
    run_id: 'run-1',
    invariant_id: `${ENV}#e1`,
    target_env_id: TARGET,
    outcome: 'blocked',
    detail: detail(),
    ...overrides,
  });

  it('retries of one attempt upsert a single row', () => {
    const test = withInvariant();
    call(test, ctx => mod.record_rule_application(ctx, application({ outcome: 'pre_hardened', detail: detail({ score_unhardened: null }) })));
    const first = test.db.rule_application.application_key.find(`run-1:${ENV}#e1->${TARGET}`)!;
    call(test, ctx => mod.record_rule_application(ctx, application()));
    call(test, ctx => mod.record_rule_application(ctx, application()));
    expect(test.db.rule_application.count()).toBe(1n);
    const row = test.db.rule_application.application_key.find(`run-1:${ENV}#e1->${TARGET}`)!;
    expect(row.outcome).toBe('blocked');
    expect(row.created_at.microsSinceUnixEpoch).toBe(first.created_at.microsSinceUnixEpoch);
  });

  it('keeps separate attempts distinct by run_id', () => {
    const test = withInvariant();
    call(test, ctx => mod.record_rule_application(ctx, application({ run_id: 'run-1', outcome: 'not_blocked' })));
    call(test, ctx => mod.record_rule_application(ctx, application({ run_id: 'run-2', outcome: 'blocked' })));
    expect(test.db.rule_application.count()).toBe(2n);
    expect([...test.db.rule_application.run_id.filter('run-2')][0]!.outcome).toBe('blocked');
  });

  it('requires a versioned JSON detail and existing rows', () => {
    const test = withInvariant();
    expect(() => call(test, ctx => mod.record_rule_application(ctx, application({ detail: 'not json' })))).toThrow(/JSON/);
    expect(() => call(test, ctx => mod.record_rule_application(ctx, application({ detail: '{"score": 1}' })))).toThrow(/"v": 1/);
    expect(() => call(test, ctx => mod.record_rule_application(ctx, application({ outcome: 'won' })))).toThrow(/outcome/);
    expect(() => call(test, ctx => mod.record_rule_application(ctx, application({ invariant_id: 'x#y' })))).toThrow(/no invariant/);
    expect(() => call(test, ctx => mod.record_rule_application(ctx, application({ target_env_id: 'game/unknown' })))).toThrow(/record_environment/);
    expect(test.db.rule_application.count()).toBe(0n);
  });
});

describe('clear_environment', () => {
  it('removes the env data and every application touching it, keeping the env row', () => {
    const test = harness();
    env(test);
    env(test, 'seed/other');
    env(test, TARGET, 'game', 'hardening');
    for (const [env_id, exploit_id] of [[ENV, 'e1'], [ENV, 'e2'], ['seed/other', 'e1']]) {
      call(test, ctx => mod.record_exploit(ctx, exploitArgs({ env_id, exploit_id })));
      call(test, ctx => mod.record_invariant(ctx, invariantArgs({ env_id, exploit_id })));
    }
    call(test, ctx => mod.record_rule_application(ctx, { run_id: 'r', invariant_id: `${ENV}#e1`, target_env_id: TARGET, outcome: 'blocked', detail: detail() }));
    call(test, ctx => mod.record_rule_application(ctx, { run_id: 'r', invariant_id: 'seed/other#e1', target_env_id: TARGET, outcome: 'blocked', detail: detail() }));

    call(test, ctx => mod.clear_environment(ctx, { env_id: ENV }));
    expect([...test.db.invariant.iter()].map(r => r.invariant_id)).toEqual(['seed/other#e1']);
    expect([...test.db.exploit.iter()].map(r => r.invariant_id)).toEqual(['seed/other#e1']);
    expect(test.db.invariant_embedding.count()).toBe(1n);
    expect([...test.db.rule_application.iter()].map(r => r.invariant_id)).toEqual(['seed/other#e1']);
    expect(test.db.environment.env_id.find(ENV)).toBeTruthy();

    call(test, ctx => mod.clear_environment(ctx, { env_id: TARGET }));
    expect(test.db.rule_application.count()).toBe(0n);
  });
});

describe('seed fixture', () => {
  it('loads through the reducers exactly as the seed command will', () => {
    const test = harness();
    for (const e of fixture.environments) {
      call(test, ctx => mod.record_environment(ctx, e));
    }
    for (const entry of fixture.entries) {
      call(test, ctx => mod.record_exploit(ctx, { env_id: entry.env_id, ...entry.exploit }));
      call(test, ctx =>
        mod.record_invariant(ctx, {
          env_id: entry.env_id,
          exploit_id: entry.exploit.exploit_id,
          ...entry.invariant,
          embedding_model: entry.embedding_model,
          embedding: entry.embedding,
        })
      );
    }
    for (const a of fixture.applications) {
      call(test, ctx => mod.record_rule_application(ctx, a));
    }
    expect(test.db.environment.count()).toBe(BigInt(fixture.environments.length));
    expect(test.db.invariant.count()).toBe(12n);
    expect(test.db.rule_application.count()).toBe(2n);
    const classes = new Set([...test.db.invariant.iter()].map(r => r.exploit_class));
    expect(classes.size).toBeGreaterThan(4);
    for (const row of test.db.invariant_embedding.iter()) {
      expect(row.vector).toHaveLength(384);
    }
  });
});

import { describe, expect, it } from 'vitest';
import { ConnectionId } from 'spacetimedb';
import { createModuleTestHarness, TestAuth } from 'spacetimedb/server/test-utils';
import spacetimedb, * as mod from './index';
import { harness, call } from './graph_test_support';

const guest = TestAuth.fromJwtPayload(JSON.stringify({ iss: 'external', sub: 'varun' }), new ConnectionId(8n));
function guestId(t: ReturnType<typeof harness>) {
  let id = '';
  t.withReducerTx(guest, ctx => { id = ctx.sender.toHexString(); });
  return id;
}

describe('hosted writer access', () => {
  it('initializes publisher metadata with no knowledge or fixture data', () => {
    const t = harness();
    expect(t.db.access_owner.count()).toBe(1n);
    expect(t.db.environment.count()).toBe(0n);
    expect(t.db.invariant.count()).toBe(0n);
    expect(t.db.rule.count()).toBe(0n);
    expect(t.db.similarity_edge.count()).toBe(0n);
  });
  it('fails closed before lifecycle initialization', () => {
    const t = createModuleTestHarness(spacetimedb, mod);
    expect(() => t.withReducerTx(guest, ctx => mod.rebuild_graph(ctx, {}))).toThrow(/Writer access/);
  });
  it('blocks every write reducer for an unapproved identity', () => {
    const t = harness();
    const callbacks = [
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.clear_environment(ctx, { env_id: 'hub/a' }),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.record_environment(ctx, { env_id: 'hub/a', source: 'hub', title: 'A', status: 'running' }),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.record_exploit(ctx, {} as never),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.record_invariant(ctx, {} as never),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.mark_exploit_patched(ctx, {} as never),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.record_rule_application(ctx, {} as never),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.graph_on_invariant(ctx, { invariant_id: 'a' }),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.rebuild_graph(ctx, {}),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.set_graph_config(ctx, { edge_threshold: 0.5, max_edges_per_node: 5 }),
      (ctx: Parameters<typeof mod.clear_environment>[0]) => mod.set_rule_title(ctx, { rule_id: 'other', title: 'A' }),
    ];
    for (const fn of callbacks) expect(() => t.withReducerTx(guest, fn)).toThrow(/Writer access/);
    expect(t.db.environment.count()).toBe(0n);
    expect(t.db.graph_config.count()).toBe(0n);
  });
  it('allows the publisher to grant and revoke a separate writer idempotently', () => {
    const t = harness(); const identity = guestId(t);
    for (let i = 0; i < 2; i++) call(t, ctx => mod.set_writer(ctx, { identity, enabled: true }));
    expect(t.db.access_writer.count()).toBe(1n);
    t.withReducerTx(guest, ctx => mod.record_environment(ctx, { env_id: 'hub/a', source: 'hub', title: 'A', status: 'running' }));
    t.withReducerTx(guest, ctx => mod.rebuild_graph(ctx, {}));
    expect(t.db.environment.count()).toBe(1n);
    for (let i = 0; i < 2; i++) call(t, ctx => mod.set_writer(ctx, { identity, enabled: false }));
    expect(() => t.withReducerTx(guest, ctx => mod.clear_environment(ctx, { env_id: 'hub/a' }))).toThrow(/Writer access/);
    expect(t.db.environment.count()).toBe(1n);
  });
  it('does not let writers grant access or alter owner metadata', () => {
    const t = harness(); const identity = guestId(t);
    call(t, ctx => mod.set_writer(ctx, { identity, enabled: true }));
    expect(() => t.withReducerTx(guest, ctx => mod.set_writer(ctx, { identity: '0'.repeat(64), enabled: true }))).toThrow(/publisher/);
    expect(() => call(t, ctx => mod.set_writer(ctx, { identity: 'invalid', enabled: true }))).toThrow(/hex/);
    expect(t.db.access_writer.count()).toBe(1n);
  });
});

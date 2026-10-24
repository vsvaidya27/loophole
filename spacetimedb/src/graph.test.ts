import { describe, expect, it } from 'vitest';
import spacetimedb, * as mod from './index';
import { call, harness, record, seed, snapshot, vector } from './graph_test_support';

describe('registered graph reducers against the real SpacetimeDB harness', () => {
  it('registers reducer arguments in the pusher order', () => {
    harness();
    const names = Object.fromEntries(spacetimedb.moduleDef.reducers.map(r => [r.sourceName,
      (r.params as { elements: { name: string }[] }).elements.map(e => e.name)]));
    expect(names.graph_on_invariant).toEqual(['invariant_id']);
    expect(names.rebuild_graph).toEqual([]);
    expect(names.set_graph_config).toEqual(['edge_threshold', 'max_edges_per_node']);
    expect(names.set_rule_title).toEqual(['rule_id', 'title']);
  });
  it.each(['event', 'rebuild', 'config', 'title'])('initializes config without init: %s', kind => {
    const t = harness();
    call(t, ctx => {
      if (kind === 'event') mod.graph_on_invariant(ctx, { invariant_id: 'missing' });
      if (kind === 'rebuild') mod.rebuild_graph(ctx, {});
      if (kind === 'config') mod.set_graph_config(ctx, { edge_threshold: 0.45, max_edges_per_node: 5 });
      if (kind === 'title') mod.set_rule_title(ctx, { rule_id: 'other', title: 'Custom title' });
    });
    expect(t.db.graph_config.count()).toBe(1n);
    expect(t.db.graph_config.id.find(0)!.edge_threshold).toBeCloseTo(0.45);
    expect(t.db.graph_config.id.find(0)!.max_edges_per_node).toBe(5);
  });
  it('builds rules and edges from all 12 real seed invariants', () => {
    const t = harness(); seed(t); call(t, ctx => mod.rebuild_graph(ctx, {}));
    const rows = [...t.db.invariant.iter()];
    expect(t.db.similarity_edge.count()).toBeGreaterThan(0n);
    expect(t.db.rule.count()).toBe(BigInt(new Set(rows.map(r => r.exploit_class)).size));
    for (const r of t.db.rule.iter()) {
      const members = rows.filter(i => i.exploit_class === r.rule_id);
      expect(r.member_count).toBe(members.length);
      expect(r.env_count).toBe(new Set(members.map(i => i.env_id)).size);
    }
    for (const e of t.db.similarity_edge.iter()) {
      expect(e.a_id < e.b_id).toBe(true);
      expect(e.edge_id).toBe(`${e.a_id}|${e.b_id}`);
      expect(e.score).toBeGreaterThanOrEqual(t.db.graph_config.id.find(0)!.edge_threshold);
    }
  });
  it('is exactly idempotent across retries, rebuilds and reversed notification order', () => {
    const t = harness(); seed(t); call(t, ctx => mod.rebuild_graph(ctx, {}));
    const expected = snapshot(t);
    for (const row of [...t.db.invariant.iter()].reverse()) call(t, ctx => mod.graph_on_invariant(ctx, { invariant_id: row.invariant_id }));
    expect(snapshot(t)).toEqual(expected);
    call(t, ctx => mod.rebuild_graph(ctx, {}));
    expect(snapshot(t)).toEqual(expected);
  });
  it('repairs later neighbours when an earlier embedding changes', () => {
    const t = harness(); const a = record(t, 'seed/a'); record(t, 'seed/b'); record(t, 'seed/c');
    call(t, ctx => mod.set_graph_config(ctx, { edge_threshold: 0.5, max_edges_per_node: 1 }));
    expect([...t.db.similarity_edge.iter()].map(e => e.a_id)).toEqual([a, a]);
    record(t, 'seed/a', 'e1', 'substring-match', vector(1));
    call(t, ctx => mod.graph_on_invariant(ctx, { invariant_id: a }));
    expect([...t.db.similarity_edge.iter()].map(e => e.edge_id)).toEqual(['seed/b#e1|seed/c#e1']);
    const expected = snapshot(t); call(t, ctx => mod.rebuild_graph(ctx, {})); expect(snapshot(t)).toEqual(expected);
  });
  it('updates an existing edge score without changing its identity', () => {
    const t = harness(); record(t, 'seed/a'); record(t, 'seed/b');
    call(t, ctx => mod.rebuild_graph(ctx, {}));
    const before = [...t.db.similarity_edge.iter()][0];
    const embedding = vector(); embedding[0] = 0.8; embedding[1] = 0.6;
    record(t, 'seed/b', 'e1', 'substring-match', embedding);
    call(t, ctx => mod.graph_on_invariant(ctx, { invariant_id: 'seed/b#e1' }));
    const after = [...t.db.similarity_edge.iter()][0];
    expect(after.edge_id).toBe(before.edge_id);
    expect(after.score).toBeCloseTo(0.8);
    call(t, ctx => mod.set_rule_title(ctx, { rule_id: 'substring-match', title: 'First' }));
    call(t, ctx => mod.set_rule_title(ctx, { rule_id: 'substring-match', title: 'Second' }));
    expect(t.db.rule.rule_id.find('substring-match')!.title).toBe('Second');
  });
  it('cleans deleted invariants and recomputes class changes and distinct environments', () => {
    const t = harness(); const a = record(t, 'seed/a'); record(t, 'seed/a', 'e2'); record(t, 'seed/b');
    call(t, ctx => mod.rebuild_graph(ctx, {}));
    expect(t.db.rule.rule_id.find('substring-match')!.env_count).toBe(2);
    record(t, 'seed/a', 'e1', 'parser-bypass');
    call(t, ctx => mod.graph_on_invariant(ctx, { invariant_id: a }));
    expect(t.db.rule.rule_id.find('parser-bypass')!.member_count).toBe(1);
    call(t, ctx => mod.clear_environment(ctx, { env_id: 'seed/a' }));
    call(t, ctx => mod.graph_on_invariant(ctx, { invariant_id: a }));
    expect(t.db.rule.rule_id.find('parser-bypass')).toBeNull();
    expect(t.db.rule.rule_id.find('substring-match')!.member_count).toBe(1);
    expect(t.db.similarity_edge.count()).toBe(0n);
  });
  it('persists title overrides across deletion, rebuild and recreation', () => {
    const t = harness(); record(t, 'seed/a');
    call(t, ctx => mod.set_rule_title(ctx, { rule_id: 'substring-match', title: '  Exact answer checking  ' }));
    call(t, ctx => mod.clear_environment(ctx, { env_id: 'seed/a' }));
    call(t, ctx => mod.rebuild_graph(ctx, {}));
    expect(t.db.rule.count()).toBe(0n);
    record(t, 'seed/b'); call(t, ctx => mod.rebuild_graph(ctx, {}));
    expect(t.db.rule.rule_id.find('substring-match')!.title).toBe('Exact answer checking');
  });
  it('skips missing, empty and incompatible embeddings without losing rule membership', () => {
    const t = harness(); record(t, 'seed/a'); record(t, 'seed/b', 'e1', 'substring-match', vector(), 'different-model');
    record(t, 'seed/c', 'e1', 'substring-match', [], ''); record(t, 'seed/d');
    call(t, ctx => ctx.db.invariant_embedding.invariant_id.delete('seed/d#e1'));
    call(t, ctx => mod.rebuild_graph(ctx, {}));
    expect(t.db.similarity_edge.count()).toBe(0n);
    expect(t.db.rule.rule_id.find('substring-match')!.member_count).toBe(4);
  });
  it.each([NaN, Infinity, -0.1, 1.01])('rejects threshold %s and rolls back', value => {
    const t = harness(); record(t, 'seed/a'); call(t, ctx => mod.rebuild_graph(ctx, {})); const before = snapshot(t);
    expect(() => call(t, ctx => mod.set_graph_config(ctx, { edge_threshold: value, max_edges_per_node: 5 }))).toThrow(/edge_threshold/);
    expect(snapshot(t)).toEqual(before);
  });
  it.each([-1, 1.5, NaN, 2 ** 32])('rejects edge limit %s', value => {
    const t = harness(); expect(() => call(t, ctx => mod.set_graph_config(ctx, { edge_threshold: 0.5, max_edges_per_node: value }))).toThrow(/max_edges/);
    expect(t.db.graph_config.count()).toBe(0n);
  });
  it('supports zero edges and rejects invalid titles and event IDs', () => {
    const t = harness(); record(t, 'seed/a'); record(t, 'seed/b');
    call(t, ctx => mod.set_graph_config(ctx, { edge_threshold: 0, max_edges_per_node: 0 }));
    expect(t.db.similarity_edge.count()).toBe(0n);
    for (const title of ['', ' '.repeat(4), 'x'.repeat(81)]) expect(() => call(t, ctx => mod.set_rule_title(ctx, { rule_id: 'other', title }))).toThrow(/title/);
    expect(() => call(t, ctx => mod.set_rule_title(ctx, { rule_id: 'unknown', title: 'Fine' }))).toThrow(/rule_id/);
    expect(() => call(t, ctx => mod.graph_on_invariant(ctx, { invariant_id: ' ' }))).toThrow(/invariant_id/);
  });
  it('never mutates core records', () => {
    const t = harness(); seed(t);
    const core = () => JSON.stringify([
      [...t.db.environment.iter()], [...t.db.exploit.iter()], [...t.db.invariant.iter()],
      [...t.db.invariant_embedding.iter()], [...t.db.rule_application.iter()],
    ], (_key, value) => typeof value === 'bigint' ? value.toString() : value);
    const before = core(); call(t, ctx => mod.rebuild_graph(ctx, {})); expect(core()).toBe(before);
  });
  it('handles 300 invariants with bounded edges and stable IDs', () => {
    const t = harness();
    for (let i = 0; i < 300; i++) record(t, `seed/${String(i).padStart(3, '0')}`);
    call(t, ctx => mod.rebuild_graph(ctx, {}));
    expect(t.db.similarity_edge.count()).toBe(1485n);
    expect(t.db.rule.rule_id.find('substring-match')!.member_count).toBe(300);
    const before = snapshot(t); call(t, ctx => mod.rebuild_graph(ctx, {})); expect(snapshot(t)).toEqual(before);
  }, 15000);
});

import { describe, expect, it } from 'vitest';
import { readFileSync, writeFileSync } from 'node:fs';
import { buildGraph, type GraphRows, type RuleApplicationRow } from '../../dashboard/src/graph/buildGraph';
import * as mod from './index';
import { harness, seed, call, clientRows } from './graph_test_support';

function rows(): GraphRows {
  return {
    environments: [
      { envId: 'hub/a', source: 'hub', title: 'A', status: 'patched' },
      { envId: 'game/b', source: 'game', title: 'B', status: 'hardening' },
    ],
    exploits: [{ invariantId: 'hub/a#1', envId: 'hub/a', exploitClass: 'substring-match', summary: 'Confirmed exploit' }],
    invariants: [{ invariantId: 'hub/a#1', envId: 'hub/a', exploitClass: 'substring-match', title: 'Substring rule' }],
    rules: [{ ruleId: 'substring-match', title: 'Strict answers', memberCount: 1, envCount: 1 }],
    similarityEdges: [], ruleApplications: [],
  };
}
function application(extra: Partial<RuleApplicationRow> = {}): RuleApplicationRow {
  return { applicationKey: 'run-1', invariantId: 'hub/a#1', targetEnvId: 'game/b', outcome: 'blocked', createdAt: { microsSinceUnixEpoch: 1n }, ...extra };
}
function expectNoDangling(graph: ReturnType<typeof buildGraph>) {
  const ids = new Set<string>(graph.nodes.map(n => n.id));
  for (const edge of graph.edges) { expect(ids.has(edge.source)).toBe(true); expect(ids.has(edge.target)).toBe(true); }
  expect(new Set(graph.edges.map(e => e.id)).size).toBe(graph.edges.length);
  expect(ids.size).toBe(graph.nodes.length);
}

describe('dashboard graph projection', () => {
  it('renders an empty subscription', () => {
    expect(buildGraph({ environments: [], exploits: [], invariants: [], rules: [], similarityEdges: [], ruleApplications: [] })).toEqual({ nodes: [], edges: [], diagnostics: [] });
  });
  it('keeps node identity when a pending exploit becomes an invariant', () => {
    const input = rows(); const pending = buildGraph({ ...input, invariants: [] }); const final = buildGraph(input);
    expect(pending.nodes.find(n => n.id === 'inv:hub/a#1')).toMatchObject({ pending: true, label: 'Confirmed exploit' });
    expect(final.nodes.find(n => n.id === 'inv:hub/a#1')).toMatchObject({ pending: false, label: 'Substring rule' });
    expect(final.nodes.filter(n => n.id === 'inv:hub/a#1')).toHaveLength(1);
  });
  it('retains pending nodes and drops edges when tables arrive separately', () => {
    const input = rows(); const graph = buildGraph({ ...input, environments: [], rules: [] });
    expect(graph.nodes).toHaveLength(1); expect(graph.edges).toHaveLength(0); expect(graph.diagnostics).toHaveLength(2);
    expectNoDangling(graph);
  });
  it('uses the newest attempt and a stable transfer edge ID, irrespective of ordering', () => {
    const input = rows(); input.ruleApplications = [application(), application({ applicationKey: 'run-2', createdAt: { microsSinceUnixEpoch: 2n }, outcome: 'not_blocked' })];
    const graph = buildGraph(input); const transfers = graph.edges.filter(e => e.kind === 'applied_to');
    expect(transfers).toEqual([{ id: 'applied_to:hub/a#1->game/b', kind: 'applied_to', source: 'rule:substring-match', target: 'env:game/b', outcome: 'not_blocked' }]);
    expect(buildGraph({ ...input, ruleApplications: [...input.ruleApplications].reverse() })).toEqual(graph);
  });
  it('breaks equal timestamp ties by application key and supports serialized timestamps', () => {
    const input = rows(); input.ruleApplications = [application({ applicationKey: 'a', createdAt: '2026-10-24T00:00:00Z' }), application({ applicationKey: 'z', createdAt: '1792800000000000', outcome: 'not_applicable' })];
    expect(buildGraph(input).edges.find(e => e.kind === 'applied_to')?.outcome).toBe('not_applicable');
  });
  it.each(['pre_hardened', 'blocked', 'not_blocked', 'not_applicable'])('preserves outcome %s without claiming independent verification', outcome => {
    const input = rows(); input.ruleApplications = [application({ outcome })];
    expect(buildGraph(input).edges.find(e => e.kind === 'applied_to')?.outcome).toBe(outcome);
  });
  it.each([
    { targetEnvId: 'hub/a' }, { targetEnvId: 'missing' }, { invariantId: 'missing' },
    { outcome: 'invalid' }, { createdAt: 'invalid date' },
  ])('diagnoses an invalid transfer %j', change => {
    const input = rows(); input.ruleApplications = [application(change)];
    const graph = buildGraph(input); expect(graph.edges.filter(e => e.kind === 'applied_to')).toHaveLength(0);
    expect(graph.diagnostics.length).toBeGreaterThan(0); expectNoDangling(graph);
  });
  it('does not show an older success when the latest attempt has an unknown outcome', () => {
    const input = rows(); input.ruleApplications = [application(), application({ createdAt: '2', outcome: 'invalid', applicationKey: 'new' })];
    expect(buildGraph(input).edges.filter(e => e.kind === 'applied_to')).toHaveLength(0);
  });
  it('canonicalizes duplicate similarities and rejects self, negative, NaN and dangling edges', () => {
    const input = rows(); input.invariants = [...input.invariants, { invariantId: 'game/b#1', envId: 'game/b', exploitClass: 'substring-match', title: 'Other rule' }];
    input.similarityEdges = [
      { edgeId: '1', aId: 'hub/a#1', bId: 'game/b#1', score: 0.8 },
      { edgeId: '2', aId: 'game/b#1', bId: 'hub/a#1', score: 0.9 },
      { edgeId: '3', aId: 'hub/a#1', bId: 'hub/a#1', score: 1 },
      { edgeId: '4', aId: 'hub/a#1', bId: 'game/b#1', score: -1 },
      { edgeId: '5', aId: 'hub/a#1', bId: 'game/b#1', score: NaN },
      { edgeId: '6', aId: 'missing', bId: 'game/b#1', score: 0.9 },
    ];
    const graph = buildGraph(input); expect(graph.edges.filter(e => e.kind === 'similar_to')).toHaveLength(1);
    expect(graph.edges.find(e => e.kind === 'similar_to')!.weight).toBe(0.9);
    expect(graph.diagnostics).toHaveLength(4); expectNoDangling(graph);
    expect(buildGraph({ ...input, similarityEdges: [...input.similarityEdges].reverse() })).toEqual(graph);
  });
  it('hides seed environments, pending nodes, similarities, transfers and seed-only rules', () => {
    const input = rows(); input.environments = [...input.environments, { envId: 'seed/a', source: 'seed', title: 'Seed', status: 'patched' }];
    input.invariants = [...input.invariants, { invariantId: 'seed/a#1', envId: 'seed/a', exploitClass: 'other', title: 'Seed rule' }];
    input.exploits = [...input.exploits, { invariantId: 'seed/a#pending', envId: 'seed/a', exploitClass: 'other', summary: 'Pending seed' }];
    input.rules = [...input.rules, { ruleId: 'other', title: 'Other', memberCount: 1, envCount: 1 }];
    input.similarityEdges = [{ edgeId: 'seed-edge', aId: 'seed/a#1', bId: 'hub/a#1', score: 0.8 }];
    input.ruleApplications = [application({ invariantId: 'seed/a#1' }), application({ targetEnvId: 'seed/a' })];
    const graph = buildGraph(input, { hideSeed: true });
    expect(graph.nodes.some(n => n.id.includes('seed'))).toBe(false);
    expect(graph.nodes.some(n => n.id === 'rule:other')).toBe(false);
    expect(graph.edges.filter(e => e.kind === 'applied_to' || e.kind === 'similar_to')).toHaveLength(0);
    expect(graph.diagnostics).toHaveLength(0); expectNoDangling(graph);
  });
  it('deduplicates rows and is stable under shuffled input without mutation', () => {
    const input = rows(); input.environments = [...input.environments, ...input.environments];
    input.invariants = [...input.invariants, ...input.invariants];
    const before = JSON.stringify(input); const graph = buildGraph(input);
    const shuffled = Object.fromEntries(Object.entries(input).map(([key, value]) => [key, [...value].reverse()])) as unknown as GraphRows;
    expect(buildGraph(shuffled)).toEqual(graph); expect(JSON.stringify(input)).toBe(before); expectNoDangling(graph);
  });
  it('replays the official seed through core reducers, graph reducers and dashboard projection', () => {
    const t = harness(); seed(t); call(t, ctx => mod.rebuild_graph(ctx, {}));
    const graph = buildGraph(clientRows(t));
    expectNoDangling(graph); expect(graph.diagnostics).toEqual([]);
    expect(graph.nodes.filter(n => n.kind === 'invariant')).toHaveLength(12);
    expect(new Set(graph.edges.map(e => e.kind))).toEqual(new Set(['found_in', 'instance_of', 'similar_to', 'applied_to']));
    expect(graph.edges.filter(e => e.kind === 'applied_to')).toHaveLength(2);
    const path = new URL('../../dashboard/src/graph/fixture.graph.json', import.meta.url);
    if (process.env.UPDATE_GRAPH_FIXTURE === '1') writeFileSync(path, JSON.stringify(graph, null, 2) + '\n');
    expect(graph).toEqual(JSON.parse(readFileSync(path, 'utf8')));
  });
});

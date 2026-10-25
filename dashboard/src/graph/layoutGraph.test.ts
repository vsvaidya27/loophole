import { describe, expect, it } from 'vitest';
import fixture from './fixture.graph.json';
import { layoutGraph } from './layoutGraph';
import type { GraphProjection } from './buildGraph';

const graph = fixture as GraphProjection;
describe('environment hub layout', () => {
  it('keeps every projected node exactly once and inside the canvas', () => {
    const { points, width, height } = layoutGraph(graph, 1000);
    expect(points.size).toBe(graph.nodes.length);
    for (const node of graph.nodes) {
      const point = points.get(node.id);
      expect(point).toBeDefined();
      expect(point![0]).toBeGreaterThan(0); expect(point![0]).toBeLessThan(width);
      expect(point![1]).toBeGreaterThan(0); expect(point![1]).toBeLessThan(height);
    }
  });
  it('places invariant satellites around their actual source without changing graph edges', () => {
    const before = JSON.stringify(graph);
    const { points, orbit } = layoutGraph(graph, 1000);
    for (const node of graph.nodes) {
      if (node.kind !== 'invariant') continue;
      const [x, y] = points.get(node.id)!;
      const [ex, ey] = points.get(`env:${node.envId}`)!;
      expect(Math.hypot(x - ex, y - ey)).toBeCloseTo(orbit);
    }
    expect(JSON.stringify(graph)).toBe(before);
    expect(layoutGraph(graph, 1000).points).toEqual(points);
  });
  it('retains orphan records while their source table is still arriving', () => {
    const partial: GraphProjection = { nodes: [{ id: 'inv:orphan', kind: 'invariant', label: 'Pending', envId: 'missing', exploitClass: 'multi-answer', pending: true }], edges: [], diagnostics: [] };
    const { points } = layoutGraph(partial, 400);
    expect(points.has('inv:orphan')).toBe(true);
    expect(points.has('env:missing')).toBe(false);
  });
  it('expands crowded hubs so satellite centers remain separated', () => {
    const crowded: GraphProjection = { nodes: [{ id: 'env:test', kind: 'environment', label: 'Test', source: 'test', status: 'hardening' }, ...Array.from({ length: 40 }, (_, i) => ({ id: `inv:${i}` as const, kind: 'invariant' as const, label: String(i), envId: 'test', exploitClass: 'multi-answer', pending: false }))], edges: [], diagnostics: [] };
    const { points } = layoutGraph(crowded, 800);
    const values = [...points.entries()].filter(([id]) => id.startsWith('inv:')).map(([, point]) => point);
    for (let i = 0; i < values.length; i++) for (let j = i + 1; j < values.length; j++) expect(Math.hypot(values[i][0] - values[j][0], values[i][1] - values[j][1])).toBeGreaterThan(36);
  });
});

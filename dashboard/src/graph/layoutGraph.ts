import type { GraphProjection } from './buildGraph';

/** Stable environment hubs with invariant satellites; every projected node keeps its identity. */
export function layoutGraph(graph: GraphProjection, availableWidth: number) {
  const environments = graph.nodes.filter(n => n.kind === 'environment');
  const invariants = graph.nodes.filter(n => n.kind === 'invariant');
  const rules = graph.nodes.filter(n => n.kind === 'rule');
  const maxMembers = Math.max(1, ...environments.map(env => invariants.filter(inv => `env:${inv.envId}` === env.id).length));
  const orbit = Math.max(96, maxMembers * 38 / (2 * Math.PI));
  const cellWidth = Math.max(360, orbit * 2 + 150), cellHeight = Math.max(330, orbit * 2 + 145);
  const width = Math.max(760, cellWidth * 2, availableWidth);
  const columns = Math.max(2, Math.floor(width / cellWidth));
  const rows = Math.ceil(environments.length / columns);
  const points = new Map<string, [number, number]>();
  environments.forEach((env, index) => {
    const x = (index % columns + .5) * width / columns;
    const y = 45 + cellHeight / 2 + Math.floor(index / columns) * cellHeight;
    points.set(env.id, [x, y]);
    const members = invariants.filter(inv => `env:${inv.envId}` === env.id);
    members.forEach((inv, i) => {
      const angle = -Math.PI / 2 + 2 * Math.PI * i / Math.max(1, members.length);
      points.set(inv.id, [x + Math.cos(angle) * orbit, y + Math.sin(angle) * orbit]);
    });
  });
  const orphans = invariants.filter(inv => !points.has(inv.id));
  const orphanColumns = Math.max(1, Math.floor(width / 100));
  orphans.forEach((inv, i) => points.set(inv.id, [60 + i % orphanColumns * 100, 80 + rows * cellHeight + Math.floor(i / orphanColumns) * 70]));
  const ruleStart = 120 + rows * cellHeight + Math.ceil(orphans.length / orphanColumns) * 70;
  const ruleColumns = Math.max(1, Math.floor(width / 190));
  rules.forEach((rule, i) => {
    const rowCount = Math.min(ruleColumns, rules.length - Math.floor(i / ruleColumns) * ruleColumns);
    points.set(rule.id, [(i % ruleColumns + .5) * width / rowCount, ruleStart + Math.floor(i / ruleColumns) * 100]);
  });
  return { width, height: Math.max(520, ruleStart + Math.ceil(rules.length / ruleColumns) * 100), points, orbit };
}


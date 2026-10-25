import type { GraphProjection, GraphNode } from './buildGraph';

const NS = 'http://www.w3.org/2000/svg';
const palette = ['#f0b96b', '#a88bfa', '#62cbd3', '#7ca5ff', '#ea92bb', '#cadb7c', '#ef946c'];
function element<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}, content?: string) {
  const el = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
  if (content !== undefined) el.textContent = content;
  return el;
}
function environmentName(node: GraphNode) {
  if (node.kind !== 'environment') return node.label;
  if (node.id.includes('/ai-') && node.label.toLowerCase().includes('arithmetic')) return 'Generated arithmetic';
  if (node.id.includes('/scripted-')) return node.id.replace(/^env:game\/scripted-\d+-\d+-/, '').replaceAll('_', ' ');
  return node.label;
}
function wrap(value: string, max = 25) {
  const lines: string[] = []; let line = '';
  for (const word of value.split(' ')) {
    if (line && (line + ' ' + word).length > max) { lines.push(line); line = word; }
    else line += (line ? ' ' : '') + word;
  }
  if (line) lines.push(line);
  return lines;
}

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

/** Uses the existing projection and selection contract; no simulation or new data connection. */
export function renderGraph(container: HTMLElement, graph: GraphProjection, selected: string | undefined, onSelect: (id: string) => void) {
  const connected = new Set<string>(selected ? [selected] : []);
  for (const edge of graph.edges) if (edge.source === selected || edge.target === selected) { connected.add(edge.source); connected.add(edge.target); }
  for (const node of graph.nodes) if (node.kind === 'invariant' && connected.has(node.id)) { connected.add(`rule:${node.exploitClass}`); connected.add(`env:${node.envId}`); }
  if (selected?.startsWith('rule:')) for (const node of graph.nodes) if (node.kind === 'invariant' && `rule:${node.exploitClass}` === selected) { connected.add(node.id); connected.add(`env:${node.envId}`); }
  const findings = graph.nodes.filter(n => n.kind === 'invariant');
  const classes = [...new Set(findings.map(n => n.exploitClass))].sort();
  const classColor = (name: string) => palette[Math.max(0, classes.indexOf(name)) % palette.length];
  let lastWidth = -1;
  function draw() {
    const measured = container.clientWidth;
    if (measured === lastWidth) return;
    lastWidth = measured;
    const { width, height, points, orbit } = layoutGraph(graph, measured);
    const svg = element('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'group', 'aria-label': 'Live invariant network. Environments are central hubs, surrounded by their recorded failures. Shared rule families connect below.' });
    svg.classList.add('network-svg');
    const defs = element('defs');
    const glow = element('filter', { id: 'node-glow', x: '-100%', y: '-100%', width: '300%', height: '300%' });
    glow.append(element('feGaussianBlur', { stdDeviation: 6 })); defs.append(glow);
    const arrow = element('marker', { id: 'transfer-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto' });
    arrow.append(element('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#63d6ad' })); defs.append(arrow); svg.append(defs);
    for (const env of graph.nodes.filter(n => n.kind === 'environment')) {
      const [x, y] = points.get(env.id)!;
      const orbitGroup = element('g', { class: `environment-orbits${selected && !connected.has(env.id) ? ' subdued' : ''}`, 'aria-hidden': 'true' });
      orbitGroup.append(element('circle', { cx: x, cy: y, r: orbit, class: 'satellite-orbit' }));
      orbitGroup.append(element('circle', { cx: x, cy: y, r: 52, class: 'hub-orbit' }));
      svg.append(orbitGroup);
    }
    const edges = element('g', { class: 'network-edges' }); svg.append(edges);
    for (const edge of graph.edges) {
      const a = points.get(edge.source), b = points.get(edge.target); if (!a || !b) continue;
      const [x1, y1] = a, [x2, y2] = b, length = Math.hypot(x2 - x1, y2 - y1) || 1;
      const source = graph.nodes.find(n => n.id === edge.source), target = graph.nodes.find(n => n.id === edge.target);
      const padA = source?.kind === 'environment' ? 37 : 17, padB = target?.kind === 'environment' ? 39 : 17;
      const sx = x1 + (x2 - x1) / length * padA, sy = y1 + (y2 - y1) / length * padA;
      const tx = x2 - (x2 - x1) / length * padB, ty = y2 - (y2 - y1) / length * padB;
      const bend = edge.kind === 'found_in' ? 0 : edge.kind === 'applied_to' ? 60 : -26;
      const active = !selected || (connected.has(edge.source) && connected.has(edge.target));
      const path = element('path', { d: `M ${sx} ${sy} Q ${(sx + tx) / 2 - (ty - sy) / length * bend} ${(sy + ty) / 2 + (tx - sx) / length * bend} ${tx} ${ty}`, class: `network-edge ${edge.kind}${active ? '' : ' subdued'}${edge.outcome ? ` outcome-${edge.outcome}` : ''}` });
      if (edge.kind === 'found_in' && source?.kind === 'invariant') path.style.stroke = classColor(source.exploitClass);
      if (edge.kind === 'applied_to') path.setAttribute('marker-end', 'url(#transfer-arrow)');
      const meaning = { found_in: 'Failure recorded in this environment', instance_of: 'Member of this shared rule family', applied_to: `Transfer test: ${edge.outcome}`, similar_to: `Similarity ${edge.weight?.toFixed(2)}; not proof of transfer` };
      path.append(element('title', {}, meaning[edge.kind])); edges.append(path);
    }
    const findingIndex = new Map(findings.map((n, i) => [n.id, i + 1]));
    for (const node of graph.nodes) {
      const [x, y] = points.get(node.id)!;
      const color = node.kind === 'invariant' ? classColor(node.exploitClass) : node.kind === 'rule' ? '#ac93ee' : ['patched', 'robust', 'done'].includes(node.status) ? '#75dec0' : '#8daafa';
      const radius = node.kind === 'environment' ? 34 : node.kind === 'rule' ? 17 : 14;
      const group = element('g', { class: `network-node ${node.kind}${selected === node.id ? ' selected' : ''}${selected && !connected.has(node.id) ? ' subdued' : ''}`, role: 'button', tabindex: 0, 'aria-label': `${node.kind}: ${node.label}`, 'aria-pressed': String(selected === node.id), 'data-node-id': node.id, style: `--node-color:${color}` });
      group.append(element('circle', { cx: x, cy: y, r: radius + 5, fill: color, opacity: .22, filter: 'url(#node-glow)', class: 'node-glow' }));
      group.append(element('circle', { cx: x, cy: y, r: radius + 4, class: 'node-halo' }));
      group.append(element('circle', { cx: x, cy: y, r: radius, class: 'node-core' }));
      if (node.kind === 'environment') {
        const initials = environmentName(node).split(/\s+/).map(word => word[0]).slice(0, 2).join('').toUpperCase();
        group.append(element('text', { x, y: y + 6, 'text-anchor': 'middle', class: 'hub-initials' }, initials));
        const lines = wrap(environmentName(node), 27).slice(0, 2);
        lines.forEach((line, i) => group.append(element('text', { x, y: y + orbit + 43 + i * 17, 'text-anchor': 'middle', class: 'environment-label' }, line)));
        const origin = node.id.includes('/scripted-') ? 'Scripted calibration' : node.id.includes('/ai-') ? 'Model-generated pilot' : node.source;
        group.append(element('text', { x, y: y + orbit + 48 + lines.length * 17, 'text-anchor': 'middle', class: 'environment-meta' }, `${origin} · ${node.status}`));
      } else if (node.kind === 'invariant') {
        group.append(element('text', { x, y: y + 3, 'text-anchor': 'middle', class: 'invariant-number' }, String(findingIndex.get(node.id))));
        const dx = x - (points.get(`env:${node.envId}`)?.[0] ?? x), dy = y - (points.get(`env:${node.envId}`)?.[1] ?? y);
        const side = Math.abs(dx) > 45;
        group.append(element('text', { x: side ? x + (dx > 0 ? 24 : -24) : x, y: side ? y + 4 : y + (dy > 0 ? 31 : -25), 'text-anchor': side ? dx > 0 ? 'start' : 'end' : 'middle', class: 'invariant-label' }, `I${findingIndex.get(node.id)}`));
      } else {
        group.append(element('text', { x, y: y + 5, 'text-anchor': 'middle', class: 'rule-symbol' }, '◇'));
        wrap(node.label, 25).slice(0, 2).forEach((line, i) => group.append(element('text', { x, y: y + 35 + i * 15, 'text-anchor': 'middle', class: 'cluster-title' }, line)));
      }
      group.append(element('title', {}, `${node.label}\n${node.id}`));
      const choose = () => onSelect(node.id); group.addEventListener('click', choose);
      group.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(); } });
      svg.append(group);
    }
    container.replaceChildren(svg);
  }
  draw(); const observer = new ResizeObserver(draw); observer.observe(container);
  return () => observer.disconnect();
}

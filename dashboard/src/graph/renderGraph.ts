import type { GraphProjection, GraphNode } from './buildGraph';

const NS = 'http://www.w3.org/2000/svg';
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
  return node.label.replace(' · model-generated', '').replaceAll('_', ' ');
}
function wrap(text: string, max = 23) {
  const lines: string[] = []; let line = '';
  for (const word of text.split(' ')) {
    if (line && (line + ' ' + word).length > max) { lines.push(line); line = word; }
    else line += (line ? ' ' : '') + word;
  }
  if (line) lines.push(line);
  return lines;
}

/** Environments remain unique; each invariant belongs to its actual rule family. */
export function renderGraph(container: HTMLElement, graph: GraphProjection, selected: string | undefined,
  onSelect: (id: string) => void) {
  const connected = new Set<string>(selected ? [selected] : []);
  for (const edge of graph.edges) if (edge.source === selected || edge.target === selected) {
    connected.add(edge.source); connected.add(edge.target);
  }
  for (const node of graph.nodes) if (node.kind === 'invariant' && connected.has(node.id)) connected.add(`rule:${node.exploitClass}`);
  const chosenRule = graph.nodes.find(n => n.id === selected && n.kind === 'rule');
  if (chosenRule) for (const node of graph.nodes) if (node.kind === 'invariant' && `rule:${node.exploitClass}` === chosenRule.id) {
    connected.add(node.id); connected.add(`env:${node.envId}`);
  }
  const environments = graph.nodes.filter(n => n.kind === 'environment');
  const rules = graph.nodes.filter(n => n.kind === 'rule');
  const findings = graph.nodes.filter(n => n.kind === 'invariant');
  let lastWidth = -1;
  function draw() {
    const width = Math.max(620, container.clientWidth);
    if (width === lastWidth) return;
    lastWidth = width;
    const height = Math.max(600, rules.length * 390 + 160, Math.ceil(environments.length / 2) * 220 + 100);
    const cx = width / 2;
    const svg = element('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'group', 'aria-label': 'Entire knowledge store: environment nodes linked to invariants inside shared rule clusters' });
    svg.classList.add('network-svg');
    const defs = element('defs');
    const gradient = element('radialGradient', { id: 'rule-wash' });
    gradient.append(element('stop', { offset: '0%', 'stop-color': '#e8e2ff', 'stop-opacity': '.7' }), element('stop', { offset: '100%', 'stop-color': '#f4f1fc', 'stop-opacity': '.65' }));
    const arrow = element('marker', { id: 'transfer-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto' });
    arrow.append(element('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#178577' }));
    defs.append(gradient, arrow); svg.append(defs);
    const points = new Map<string, [number, number]>();
    const ry = 174, rx = Math.min(174, width * .235);
    environments.forEach((env, index) => {
      const pair = Math.floor(index / 2), rows = Math.ceil(environments.length / 2);
      points.set(env.id, [width * (index % 2 === 0 ? .135 : .865), rows === 1 ? height / 2 : 140 + pair * (height - 280) / (rows - 1)]);
    });
    rules.forEach((rule, index) => {
      const cy = rules.length === 1 ? height / 2 : 230 + index * 390;
      points.set(rule.id, [cx, cy]);
      const region = element('g', { class: `rule-region${selected && !connected.has(rule.id) ? ' subdued' : ''}`, role: 'button', tabindex: 0, 'aria-label': `Rule family: ${rule.label}` });
      region.append(element('ellipse', { cx, cy, rx, ry, fill: 'url(#rule-wash)' }));
      region.append(element('text', { x: cx, y: cy - ry + 31, 'text-anchor': 'middle', class: 'cluster-eyebrow' }, 'SHARED RULE FAMILY'));
      wrap(rule.label, 25).forEach((line, i) => region.append(element('text', { x: cx, y: cy - ry + 55 + i * 17, 'text-anchor': 'middle', class: 'cluster-title' }, line)));
      region.append(element('text', { x: cx, y: cy + ry - 24, 'text-anchor': 'middle', class: 'cluster-count' }, `${rule.memberCount} invariants · ${rule.envCount} environments`));
      region.append(element('title', {}, `${rule.label}. The region contains related invariants, not environments. Select to inspect.`));
      const choose = () => onSelect(rule.id); region.addEventListener('click', choose);
      region.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(); } });
      svg.append(region);
      const members = findings.filter(n => `rule:${n.exploitClass}` === rule.id);
      members.forEach((inv, i) => {
        const env = points.get(`env:${inv.envId}`);
        const peers = members.filter(n => n.envId === inv.envId);
        const slot = peers.findIndex(n => n.id === inv.id) - (peers.length - 1) / 2;
        const angle = env ? Math.atan2((env[1] - cy) / ry, (env[0] - cx) / rx) + slot * .65 : 2 * Math.PI * i / Math.max(1, members.length);
        points.set(inv.id, [cx + rx * .64 * Math.cos(angle), cy + 15 + ry * .49 * Math.sin(angle)]);
      });
    });
    let orphan = 0;
    for (const inv of findings) if (!points.has(inv.id)) points.set(inv.id, [cx, height - 80 - orphan++ * 55]);
    const edgeLayer = element('g', { class: 'network-edges' }); svg.append(edgeLayer);
    for (const edge of graph.edges) {
      // Containment in the shaded rule region represents membership.
      if (edge.kind === 'instance_of') continue;
      const a = points.get(edge.source), b = points.get(edge.target);
      if (!a || !b) continue;
      const [x1, y1] = a, [x2, y2] = b;
      const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
      const from = graph.nodes.find(n => n.id === edge.source), to = graph.nodes.find(n => n.id === edge.target);
      const padA = from?.kind === 'environment' ? 24 : 12, padB = to?.kind === 'environment' ? 28 : 12;
      const sx = x1 + dx / len * padA, sy = y1 + dy / len * padA, tx = x2 - dx / len * padB, ty = y2 - dy / len * padB;
      const transfer = edge.kind === 'applied_to';
      const curvature = transfer ? 62 : edge.kind === 'similar_to' ? -25 : 0;
      const path = element('path', { d: `M ${sx} ${sy} Q ${(sx + tx) / 2 - dy / len * curvature} ${(sy + ty) / 2 + dx / len * curvature} ${tx} ${ty}`,
        class: `network-edge ${edge.kind}${selected && edge.source !== selected && edge.target !== selected ? ' subdued' : ''}` });
      if (transfer) path.setAttribute('marker-end', 'url(#transfer-arrow)');
      const meanings = { found_in: 'Invariant extracted from this environment', applied_to: `Tested transfer: ${edge.outcome}`, similar_to: `Embedding similarity ${edge.weight?.toFixed(2)}; not proof of transfer` };
      path.append(element('title', {}, meanings[edge.kind])); edgeLayer.append(path);
    }
    const invariantIndex = new Map(findings.map((n, i) => [n.id, i + 1]));
    for (const node of graph.nodes.filter(n => n.kind !== 'rule')) {
      const [x, y] = points.get(node.id)!;
      const group = element('g', { class: `network-node ${node.kind}${selected === node.id ? ' selected' : ''}${selected && !connected.has(node.id) ? ' subdued' : ''}`,
        role: 'button', tabindex: 0, 'aria-label': `${node.kind}: ${node.label}`, 'aria-pressed': String(selected === node.id) });
      group.append(element('circle', { cx: x, cy: y, r: node.kind === 'environment' ? 24 : 12, class: 'node-halo' }));
      group.append(element('circle', { cx: x, cy: y, r: node.kind === 'environment' ? 17 : 8, class: 'node-core' }));
      if (node.kind === 'environment') {
        wrap(environmentName(node), 22).forEach((line, i, lines) => group.append(element('text', { x, y: y - 39 - (lines.length - 1 - i) * 17, 'text-anchor': 'middle', class: 'environment-label' }, line)));
        const provenance = node.id.includes('/scripted-') ? 'Scripted calibration' : (node.id.includes('/ai-') || node.label.includes('model-generated')) ? 'Model-generated pilot' : node.source;
        group.append(element('text', { x, y: y + 44, 'text-anchor': 'middle', class: 'environment-meta' }, provenance));
        group.append(element('text', { x, y: y + 60, 'text-anchor': 'middle', class: 'environment-status' }, node.status));
      } else {
        group.append(element('text', { x, y: y + 29, 'text-anchor': 'middle', class: 'invariant-label' }, `I${invariantIndex.get(node.id)}`));
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

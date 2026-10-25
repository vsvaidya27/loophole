import { useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import type { GraphNode, GraphProjection } from '../graph/buildGraph';
import { layoutGraph } from '../graph/layoutGraph';

const palette = ['#b5372f', '#7a5a92', '#2e7f7a', '#2e5f86', '#a3466c', '#6f7d34', '#b0742a'];
function environmentName(node: GraphNode) {
  if (node.kind !== 'environment') return node.label;
  if (node.id.includes('/ai-') && node.label.toLowerCase().includes('arithmetic')) return 'Generated arithmetic';
  if (node.id.includes('/scripted-')) return node.id.replace(/^env:game\/scripted-\d+-\d+-/, '').replaceAll('_', ' ');
  return node.label.replace(' · model-generated', '').replaceAll('_', ' ');
}
function wrap(value: string, max = 25) {
  const lines: string[] = [];
  let line = '';
  for (const word of value.split(' ')) {
    if (line && (line + ' ' + word).length > max) { lines.push(line); line = word; }
    else line += (line ? ' ' : '') + word;
  }
  if (line) lines.push(line);
  return lines;
}

type Props = { graph: GraphProjection; selected?: string; onSelect: (id: string) => void; containerId?: string };

/** React owns the SVG nodes, preserving focus and scroll as live records change. */
export function InvariantNetwork({ graph, selected, onSelect, containerId = 'graph' }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [availableWidth, setAvailableWidth] = useState(0);
  const id = useId();
  const glowId = `node-glow-${id}`, arrowId = `transfer-arrow-${id}`;
  useLayoutEffect(() => {
    const element = container.current!;
    const measure = () => setAvailableWidth(element.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const { width, height, points, orbit } = useMemo(() => layoutGraph(graph, availableWidth), [graph, availableWidth]);
  const connected = new Set<string>(selected ? [selected] : []);
  for (const edge of graph.edges) if (edge.source === selected || edge.target === selected) {
    connected.add(edge.source); connected.add(edge.target);
  }
  for (const node of graph.nodes) if (node.kind === 'invariant' && connected.has(node.id)) {
    connected.add(`rule:${node.exploitClass}`); connected.add(`env:${node.envId}`);
  }
  if (selected?.startsWith('rule:')) for (const node of graph.nodes) {
    if (node.kind === 'invariant' && `rule:${node.exploitClass}` === selected) { connected.add(node.id); connected.add(`env:${node.envId}`); }
  }
  const findings = graph.nodes.filter(node => node.kind === 'invariant');
  const classes = [...new Set(findings.map(node => node.exploitClass))].sort();
  const classColor = (name: string) => palette[Math.max(0, classes.indexOf(name)) % palette.length];
  const findingIndex = new Map(findings.map((node, index) => [node.id, index + 1]));
  const nodeById = new Map(graph.nodes.map(node => [node.id as string, node]));

  return <div id={containerId} className="invariant-network" ref={container}>
    {graph.nodes.length > 0 && <svg className="network-svg" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="group"
      aria-label="Live invariant network. Environments are central hubs, surrounded by their recorded failures. Shared rule families connect below.">
      <defs>
        <filter id={glowId} x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation={6} /></filter>
        <marker id={arrowId} viewBox="0 0 10 10" refX={9} refY={5} markerWidth={5} markerHeight={5} orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#2e5f86" /></marker>
      </defs>
      {graph.nodes.filter(node => node.kind === 'environment').map(env => {
        const [x, y] = points.get(env.id)!;
        return <g key={env.id} className={`environment-orbits${selected && !connected.has(env.id) ? ' subdued' : ''}`} aria-hidden="true">
          <circle cx={x} cy={y} r={orbit} className="satellite-orbit" /><circle cx={x} cy={y} r={52} className="hub-orbit" />
        </g>;
      })}
      <g className="network-edges">
        {graph.edges.map(edge => {
          const a = points.get(edge.source), b = points.get(edge.target);
          if (!a || !b) return null;
          const [x1, y1] = a, [x2, y2] = b, length = Math.hypot(x2 - x1, y2 - y1) || 1;
          const source = nodeById.get(edge.source), target = nodeById.get(edge.target);
          const padA = source?.kind === 'environment' ? 37 : 17, padB = target?.kind === 'environment' ? 39 : 17;
          const sx = x1 + (x2 - x1) / length * padA, sy = y1 + (y2 - y1) / length * padA;
          const tx = x2 - (x2 - x1) / length * padB, ty = y2 - (y2 - y1) / length * padB;
          const bend = edge.kind === 'found_in' ? 0 : edge.kind === 'applied_to' ? 60 : -26;
          const active = !selected || (connected.has(edge.source) && connected.has(edge.target));
          const meaning = { found_in: 'Failure recorded in this environment', instance_of: 'Member of this shared rule family', applied_to: `Transfer test: ${edge.outcome}`, similar_to: `Similarity ${edge.weight?.toFixed(2)}; not proof of transfer` };
          return <path key={edge.id} d={`M ${sx} ${sy} Q ${(sx + tx) / 2 - (ty - sy) / length * bend} ${(sy + ty) / 2 + (tx - sx) / length * bend} ${tx} ${ty}`}
            className={`network-edge ${edge.kind}${active ? '' : ' subdued'}${edge.outcome ? ` outcome-${edge.outcome}` : ''}`}
            style={edge.kind === 'found_in' && source?.kind === 'invariant' ? { stroke: classColor(source.exploitClass) } : undefined}
            markerEnd={edge.kind === 'applied_to' ? `url(#${arrowId})` : undefined}><title>{meaning[edge.kind]}</title></path>;
        })}
      </g>
      {graph.nodes.map(node => {
        const [x, y] = points.get(node.id)!;
        const color = node.kind === 'invariant' ? classColor(node.exploitClass) : node.kind === 'rule' ? '#7a5a92' : ['patched', 'robust', 'done'].includes(node.status) ? '#2e5f86' : '#857e76';
        const radius = node.kind === 'environment' ? 34 : node.kind === 'rule' ? 17 : 14;
        const name = environmentName(node), lines = wrap(name, 27).slice(0, 2);
        const sourcePoint = node.kind === 'invariant' ? points.get(`env:${node.envId}`) : undefined;
        const dx = x - (sourcePoint?.[0] ?? x), dy = y - (sourcePoint?.[1] ?? y), side = Math.abs(dx) > 45;
        return <g key={node.id} className={`network-node ${node.kind}${selected === node.id ? ' selected' : ''}${selected && !connected.has(node.id) ? ' subdued' : ''}`}
          role="button" tabIndex={0} aria-label={`${node.kind}: ${node.label}`} aria-pressed={selected === node.id} data-node-id={node.id}
          style={{ '--node-color': color } as CSSProperties} onClick={() => onSelect(node.id)}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(node.id); } }}>
          <circle cx={x} cy={y} r={radius + 5} fill={color} opacity={.22} filter={`url(#${glowId})`} className="node-glow" />
          <circle cx={x} cy={y} r={radius + 4} className="node-halo" /><circle cx={x} cy={y} r={radius} className="node-core" />
          {node.kind === 'environment' && <>
            <text x={x} y={y + 6} textAnchor="middle" className="hub-initials">{name.split(/\s+/).map(word => word[0]).slice(0, 2).join('').toUpperCase()}</text>
            {lines.map((line, index) => <text key={index} x={x} y={y + orbit + 43 + index * 17} textAnchor="middle" className="environment-label">{line}</text>)}
            <text x={x} y={y + orbit + 48 + lines.length * 17} textAnchor="middle" className="environment-meta">
              {node.id.includes('/scripted-') ? 'Scripted calibration' : (node.id.includes('/ai-') || node.label.includes('model-generated')) ? 'Model-generated pilot' : node.source} · {node.status}
            </text>
          </>}
          {node.kind === 'invariant' && <>
            <text x={x} y={y + 3} textAnchor="middle" className="invariant-number">{findingIndex.get(node.id)}</text>
            <text x={side ? x + (dx > 0 ? 24 : -24) : x} y={side ? y + 4 : y + (dy > 0 ? 31 : -25)} textAnchor={side ? dx > 0 ? 'start' : 'end' : 'middle'} className="invariant-label">I{findingIndex.get(node.id)}</text>
          </>}
          {node.kind === 'rule' && <>
            <text x={x} y={y + 5} textAnchor="middle" className="rule-symbol">◇</text>
            {wrap(node.label).slice(0, 2).map((line, index) => <text key={index} x={x} y={y + 35 + index * 15} textAnchor="middle" className="cluster-title">{line}</text>)}
          </>}
          <title>{`${node.label}\n${node.id}`}</title>
        </g>;
      })}
    </svg>}
  </div>;
}

import { useMemo, type KeyboardEvent } from 'react';
import type { GraphNode, GraphProjection } from '../graph/buildGraph';

const W = 820, H = 700, CX = W / 2, CY = H / 2 - 6, RING = 235, GOLDEN = 2.399963;
const FAMILY: Record<string, string> = {
  'multi-answer': 'Several answers at once', 'parser-bypass': 'Odd formatting fools the parser',
  'lenient-normalization': 'Near-misses counted as right', 'substring-match': 'Answer found anywhere in the text',
  'format-only': 'Right format, wrong answer', other: 'Other loopholes',
};
type Point = [number, number];
type Props = { graph: GraphProjection; selected?: string; onSelect: (id: string) => void; compact?: boolean };

export const familyName = (id: string, fallback?: string) => FAMILY[id] ?? fallback ?? id.replaceAll('-', ' ');

/** Short display name for an environment: the Hub name without its publisher, or the title's first part. */
function shortName(node?: GraphNode) {
  if (!node || node.kind !== 'environment') return '';
  const id = node.id.slice(4);
  if (!id.startsWith('game/') && id.includes('/')) return id.split('/')[1];
  return node.label.split(' · ')[0].replaceAll('_', ' ');
}

function lines(text: string, max = 15) {
  const out: string[] = [];
  for (const word of text.split(/\s+/)) {
    const last = out[out.length - 1];
    if (last !== undefined && (last + ' ' + word).length <= max) out[out.length - 1] = `${last} ${word}`;
    else out.push(word);
  }
  return out.length > 2 ? [out[0], `${out[1].slice(0, max - 1)}…`] : out;
}

const curve = ([x1, y1]: Point, [x2, y2]: Point, bend = 0.18) => {
  const mx = (x1 + x2) / 2 - (y2 - y1) * bend, my = (y1 + y2) / 2 + (x2 - x1) * bend;
  return `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`;
};

/** Rule families on a ring with their invariant records in sunflower clusters. */
function layout(graph: GraphProjection) {
  const invariants = graph.nodes.filter(node => node.kind === 'invariant');
  const rules = new Map(graph.nodes.filter(node => node.kind === 'rule').map(node => [node.id.slice(5), node]));
  const counts = new Map<string, number>();
  for (const inv of invariants) counts.set(inv.exploitClass, (counts.get(inv.exploitClass) ?? 0) + 1);
  const families = [...counts.keys()].sort((a, b) => counts.get(b)! - counts.get(a)! || a.localeCompare(b));
  const centres = new Map<string, Point>();
  families.forEach((family, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / families.length;
    centres.set(family, [CX + Math.cos(angle) * RING, CY + Math.sin(angle) * RING]);
  });
  const points = new Map<string, Point>();
  const placed = new Map<string, number>();
  for (const inv of [...invariants].sort((a, b) => a.id.localeCompare(b.id))) {
    const [x, y] = centres.get(inv.exploitClass)!;
    const i = placed.get(inv.exploitClass) ?? 0;
    placed.set(inv.exploitClass, i + 1);
    const r = 10 + 7.4 * Math.sqrt(i), t = i * GOLDEN;
    points.set(inv.id, [x + Math.cos(t) * r, y + Math.sin(t) * r]);
  }
  return { families, rules, counts, centres, points, invariants };
}

const press = (action: () => void) => (event: KeyboardEvent) => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(); }
};

/** The knowledge graph as a constellation. Selecting an environment, a rule, or a rule family centres it and
 *  draws beams to the records it connects to; similar rules come from recorded similarity edges only. */
export function KnowledgeConstellation({ graph, selected, onSelect, compact = false }: Props) {
  const { families, rules, counts, centres, points, invariants } = useMemo(() => layout(graph), [graph]);
  const nodes = useMemo(() => new Map(graph.nodes.map(node => [node.id as string, node])), [graph]);
  const number = useMemo(() => new Map(invariants.map((node, i) => [node.id as string, i + 1])), [invariants]);
  const similar = useMemo(() => graph.edges.filter(edge => edge.kind === 'similar_to'), [graph]);

  const node = selected ? nodes.get(selected) : undefined;
  const picked: string[] = [];
  let related: { id: string; weight: number; from: string }[] = [];
  let centre = { title: `${invariants.length} rules`, sub: `${graph.nodes.filter(n => n.kind === 'environment').length} environments` };
  let transfers: string[] = [];
  let beamsFromCentre = true;
  if (node?.kind === 'environment') {
    picked.push(...invariants.filter(inv => `env:${inv.envId}` === node.id).map(inv => inv.id));
    centre = { title: shortName(node), sub: `${picked.length} rule${picked.length === 1 ? '' : 's'} here` };
    transfers = graph.edges.filter(edge => edge.kind === 'applied_to' && edge.target === node.id).map(edge => edge.source.slice(5));
  } else if (node?.kind === 'invariant') {
    picked.push(node.id);
    centre = { title: shortName(nodes.get(`env:${node.envId}`)) || 'Source', sub: `source of I${number.get(node.id)}` };
  } else if (node?.kind === 'rule') {
    picked.push(...invariants.filter(inv => `rule:${inv.exploitClass}` === node.id).map(inv => inv.id));
    centre = { title: familyName(node.id.slice(5), node.label), sub: `${picked.length} rules` };
    beamsFromCentre = false;
  }
  if (node && node.kind !== 'rule') {
    const own = new Set(picked);
    const best = new Map<string, { weight: number; from: string }>();
    for (const edge of similar) {
      const pair = own.has(edge.source) ? [edge.source, edge.target] : own.has(edge.target) ? [edge.target, edge.source] : undefined;
      if (!pair) continue;
      const [a, b] = pair;
      if (own.has(b) || (best.get(b)?.weight ?? -1) >= (edge.weight ?? 0)) continue;
      best.set(b, { weight: edge.weight ?? 0, from: a });
    }
    related = [...best].map(([id, v]) => ({ id, ...v })).sort((x, y) => y.weight - x.weight).slice(0, 6);
  }
  const pickedSet = new Set(picked), relatedSet = new Set(related.map(r => r.id));
  const litFamilies = new Set([...picked, ...related.map(r => r.id)].map(id => (nodes.get(id) as { exploitClass?: string })?.exploitClass));
  const focus = Boolean(node);
  const centrePoint: Point = [CX, CY];
  const label = `Knowledge graph of ${invariants.length} rules in ${families.length} families.`
    + (node ? ` Selected: ${centre.title}. ${picked.length} highlighted, ${related.length} similar rules from other records.` : '');

  return <div className={`constellation-wrap${compact ? ' compact' : ''}`}>
    <svg className={`kg-constellation${focus ? ' focused' : ''}`} viewBox={`0 0 ${W} ${H}`} role="group" aria-label={label}>
      <g className="kg-similarity" aria-hidden="true">
        {!compact && similar.map(edge => {
          const a = points.get(edge.source), b = points.get(edge.target);
          return a && b ? <path key={edge.id} d={curve(a, b, 0.08)} /> : null;
        })}
      </g>
      {families.map(family => {
        const [x, y] = centres.get(family)!;
        const radius = 14 + 7.4 * Math.sqrt(counts.get(family)!), above = y < CY;
        const ly = above ? y - radius - 24 : y + radius + 22;
        const rule = rules.get(family);
        const lit = litFamilies.has(family) || selected === `rule:${family}`;
        const select = () => rule && onSelect(rule.id);
        return <g key={family} className={`kg-family${lit ? ' lit' : ''}${rule ? ' selectable' : ''}`}
          role={rule ? 'button' : undefined} tabIndex={rule ? 0 : undefined} aria-pressed={rule ? selected === rule.id : undefined}
          aria-label={rule ? `Rule family: ${familyName(family, rule.label)}, ${counts.get(family)} rules` : undefined}
          onClick={select} onKeyDown={press(select)}>
          <circle cx={x} cy={y} r={radius} className="kg-halo" />
          <text x={x} y={ly} textAnchor="middle" className="kg-family-name">{familyName(family, rule?.label)}</text>
          {!compact && <text x={x} y={ly + 17} textAnchor="middle" className="kg-family-count">{counts.get(family)} {counts.get(family) === 1 ? 'rule' : 'rules'}</text>}
        </g>;
      })}
      {invariants.map(inv => {
        const [x, y] = points.get(inv.id)!;
        const state = pickedSet.has(inv.id) ? ' picked' : relatedSet.has(inv.id) ? ' related' : focus ? ' quiet' : '';
        const select = () => onSelect(inv.id);
        return <circle key={inv.id} cx={x} cy={y} r={state === ' picked' ? 6.5 : state === ' related' ? 5.5 : 3.6}
          className={`kg-dot${state}`} data-constellation-id={inv.id} role="button" tabIndex={state && state !== ' quiet' ? 0 : -1}
          aria-label={`I${number.get(inv.id)}: ${inv.label}`} onClick={select} onKeyDown={press(select)}><title>{`I${number.get(inv.id)} · ${inv.label}`}</title></circle>;
      })}
      {focus && <g className="kg-beams" key={selected} aria-hidden="true">
        {transfers.map((family, i) => centres.get(family) && <path key={`t-${family}`} d={curve(centres.get(family)!, centrePoint, 0.1)} pathLength={1} className="kg-beam transfer" style={{ animationDelay: `${i * 120}ms` }} />)}
        {beamsFromCentre && picked.map((id, i) => <path key={id} d={curve(centrePoint, points.get(id)!, i % 2 ? 0.12 : -0.12)} pathLength={1}
          className="kg-beam" style={{ animationDelay: `${Math.min(i, 12) * 70}ms` }} />)}
        {related.map((r, i) => <path key={`r-${r.id}`} d={curve(points.get(r.from)!, points.get(r.id)!, 0.14)} pathLength={1}
          className="kg-beam related" style={{ animationDelay: `${400 + i * 110}ms` }} />)}
        {[...(node?.kind === 'invariant' ? picked : []), ...related.map(r => r.id)].map((id, i) => {
          const [x, y] = points.get(id)!;
          return <g key={`tag-${id}`} className={`kg-tag${pickedSet.has(id) ? ' own' : ''}`} transform={`translate(${x} ${y})${compact ? ' scale(1.45)' : ''}`} style={{ animationDelay: `${500 + i * 110}ms` }}>
            <rect x={-15} y={-27} width={30} height={17} rx={8.5} /><text y={-14.5} textAnchor="middle">I{number.get(id)}</text>
          </g>;
        })}
      </g>}
      <g className={`kg-centre${focus ? ' active' : ''}`} transform={`translate(${CX} ${CY})`} aria-hidden="true">
        <circle r={56} />
        {lines(centre.title).map((line, i, all) => <text key={i} y={(i - (all.length - 1) / 2) * 16 - 3} textAnchor="middle" className="kg-centre-title">{line}</text>)}
        <text y={lines(centre.title).length * 8 + 12} textAnchor="middle" className="kg-centre-sub">{centre.sub}</text>
      </g>
    </svg>
    {!compact && <p className="constellation-caption" aria-live="polite">{
      node?.kind === 'invariant' ? `I${number.get(node.id)} and the ${related.length} records most similar to it. Similarity suggests where a defense may carry over; only a transfer test shows that it does.`
      : node?.kind === 'environment' ? `${picked.length} rule${picked.length === 1 ? '' : 's'} found in this environment, with the ${related.length} most similar records from elsewhere${transfers.length ? ` and ${transfers.length} rule famil${transfers.length === 1 ? 'y' : 'ies'} tested here (dashed)` : ''}.`
      : node?.kind === 'rule' ? `Every rule in this family, from ${new Set(picked.map(id => (nodes.get(id) as { envId?: string })?.envId)).size} environments.`
      : 'Each dot is a rule learned from a confirmed reward failure, grouped by how it cheats. Pick an environment, a family or a dot.'
    }</p>}
  </div>;
}

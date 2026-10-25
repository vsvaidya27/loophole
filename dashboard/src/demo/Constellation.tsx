import { report } from './transfer';
import { useMemo } from 'react';
import { FAMILY, type DemoData } from './data';

const W = 820, H = 700, CX = W / 2, CY = H / 2 - 6, RING = 235, GOLDEN = 2.399963;

export type GraphPhase = 'game' | 'graph' | 'query' | 'handoff' | 'loop' | 'learned';

/** Rule families on a ring, their invariant records in sunflower clusters, the new game at the centre. */
function layout(data: DemoData) {
  const families = [...data.graph_before.rules].sort((a, b) => b.member_count - a.member_count);
  const centres = new Map<string, [number, number, number]>();
  families.forEach((rule, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / families.length;
    centres.set(rule.rule_id, [CX + Math.cos(angle) * RING, CY + Math.sin(angle) * RING, angle]);
  });
  const points = new Map<string, [number, number]>();
  const counts = new Map<string, number>();
  const place = (id: string, family: string) => {
    const [x, y] = centres.get(family) ?? [CX, CY];
    const i = counts.get(family) ?? 0;
    counts.set(family, i + 1);
    const r = 10 + 7.4 * Math.sqrt(i), t = i * GOLDEN;
    points.set(id, [x + Math.cos(t) * r, y + Math.sin(t) * r]);
  };
  for (const inv of [...data.graph_before.invariants].sort((a, b) => a.invariant_id.localeCompare(b.invariant_id))) place(inv.invariant_id, inv.exploit_class);
  for (const inv of data.learned.invariants) place(inv.invariant_id, inv.exploit_class);
  return { families, centres, points };
}

const curve = ([x1, y1]: [number, number], [x2, y2]: [number, number], bend = 0.18) => {
  const mx = (x1 + x2) / 2 - (y2 - y1) * bend, my = (y1 + y2) / 2 + (x2 - x1) * bend;
  return `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`;
};

/** Act 1: the game's forty numbers, and what the recorded loophole reply does to them. */
function NumberLine({ data, flaw }: { data: DemoData; flaw: boolean }) {
  const attempt = data.rounds[0].attempts.find(a => a.confirmed) ?? data.rounds[0].attempts[0];
  const listed = new Set((attempt.replies[0].match(/\d+/g) ?? []).map(Number));
  const cell = 24, gap = 5, per = 20, left = CX - (per * (cell + gap) - gap) / 2, top = CY + 60;
  return <g className={`number-line${flaw ? ' flaw' : ''}`}>
    <text x={CX} y={top - 18} textAnchor="middle" className="line-caption">
      {flaw ? `One reply lists ${listed.size} numbers. The grader counts every one as a guess.` : 'A hidden number, somewhere from 1 to 40. Seven guesses to find it.'}
    </text>
    {Array.from({ length: data.game.high - data.game.low + 1 }, (_, i) => {
      const n = data.game.low + i, x = left + (i % per) * (cell + gap), y = top + Math.floor(i / per) * (cell + gap);
      const hit = flaw && listed.has(n), secret = flaw && n === attempt.secret;
      return <g key={n} className={`cell${hit ? ' hit' : ''}${secret ? ' secret' : ''}`} style={{ animationDelay: `${i * 18}ms` }}>
        <rect x={x} y={y} width={cell} height={cell} rx={5} /><text x={x + cell / 2} y={y + 16} textAnchor="middle">{n}</text>
      </g>;
    })}
    {flaw && <text x={CX} y={top + 2 * (cell + gap) + 26} textAnchor="middle" className="line-caption verdict-line">
      The hidden number was {attempt.secret}. Paid in full on the first turn, without any searching.
    </text>}
  </g>;
}

export function Constellation({ data, phase, hardened, flaw = false }: { data: DemoData; phase: GraphPhase; hardened: boolean; flaw?: boolean }) {
  const { families, centres, points } = useMemo(() => layout(data), [data]);
  const retrieved = data.retrieval.matches;
  const order = new Map(retrieved.map((m, i) => [m.id, i + 1]));
  const offered = new Set(data.retrieval.offered_to_prompt);
  const memberCount = new Map<string, number>();
  for (const inv of data.graph_before.invariants) memberCount.set(inv.exploit_class, (memberCount.get(inv.exploit_class) ?? 0) + 1);
  const showGraph = phase !== 'game';
  const focus = phase === 'query' || phase === 'handoff' || phase === 'loop' || phase === 'learned';
  const showLearned = phase === 'learned';
  const centre: [number, number] = [CX, CY];
  const label = `Knowledge graph of ${data.graph_before.invariants.length} rules from ${data.graph_before.environments.length} earlier environments.`
    + (focus ? ` ${retrieved.length} candidates were retrieved; only the Mini Sudoku rule was selected for adaptation.` : '')
    + (showLearned ? ' One validated application links the Mini Sudoku rule to Number hunt; no new invariant is added.' : '');

  return <svg className={`constellation phase-${phase}`} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
    <g className="graph-layer" opacity={showGraph ? 1 : 0}>
      <g className="similarity">
        {data.graph_before.similarity_edges.map(edge => {
          const a = points.get(edge.a_id), b = points.get(edge.b_id);
          return a && b ? <path key={`${edge.a_id}|${edge.b_id}`} d={curve(a, b, 0.08)} /> : null;
        })}
      </g>
      {families.map(rule => {
        const [x, y] = centres.get(rule.rule_id)!;
        const radius = 14 + 7.4 * Math.sqrt(rule.member_count), above = y < CY;
        const ly = above ? y - radius - 24 : y + radius + 22;
        const lit = focus && retrieved.some(m => m.exploit_class === rule.rule_id);
        const count = memberCount.get(rule.rule_id) ?? 0;
        return <g key={rule.rule_id} className={`family${lit ? ' lit' : ''}`}>
          <circle cx={x} cy={y} r={radius} className="family-halo" />
          <text x={x} y={ly} textAnchor="middle" className="family-name">{FAMILY[rule.rule_id] ?? rule.title}</text>
          <text x={x} y={ly + 17} textAnchor="middle" className="family-count">{count} {count === 1 ? 'rule' : 'rules'}</text>
        </g>;
      })}
      {data.graph_before.invariants.map(inv => {
        const [x, y] = points.get(inv.invariant_id)!;
        const n = order.get(inv.invariant_id);
        return <circle key={inv.invariant_id} cx={x} cy={y} r={n && focus ? 6.5 : 3.6}
          className={`rule-dot${n && focus ? ' picked' : ''}${focus && !n ? ' quiet' : ''}`}><title>{inv.title}</title></circle>;
      })}
    </g>
    {focus && <g className="beams">
      {retrieved.filter(m => !showLearned || m.id === report.source.invariant_id).map((m, i) => {
        const p = points.get(m.id);
        return p ? <path key={m.id} d={curve(centre, p, i % 2 ? 0.12 : -0.12)} pathLength={1}
          className={`beam${offered.has(m.id) ? ' offered' : ''}`} style={{ animationDelay: `${i * 160}ms` }} /> : null;
      })}
      {retrieved.filter(m => !showLearned || m.id === report.source.invariant_id).map(m => {
        const p = points.get(m.id);
        return p ? <g key={`${m.id}-tag`} className="pick-tag" transform={`translate(${p[0]} ${p[1]})`}>
          <circle r={11} /><text y={4} textAnchor="middle">{order.get(m.id)}</text>
        </g> : null;
      })}
    </g>}
    {showLearned && <text x={CX} y={CY + 85} textAnchor="middle" className="family-name">Mini Sudoku rule → Number hunt · blocked</text>}
    {showLearned && <g className="learned">
      {data.learned.similarity_edges.map(edge => {
        const a = points.get(edge.a_id), b = points.get(edge.b_id);
        return a && b ? <path key={`${edge.a_id}|${edge.b_id}`} d={curve(a, b, 0.1)} pathLength={1} className="learned-edge" /> : null;
      })}
      {data.learned.invariants.map(inv => {
        const [x, y] = points.get(inv.invariant_id)!;
        return <g key={inv.invariant_id} className="learned-dot" transform={`translate(${x} ${y})`}>
          <circle r={11} className="ring" /><circle r={5.5} className="core" /><title>{inv.title}</title>
        </g>;
      })}
    </g>}
    {phase === 'game' && <NumberLine data={data} flaw={flaw} />}
    <g className={`new-game${hardened ? ' hardened' : ''}`} transform={`translate(${CX} ${phase === 'game' ? CY - 90 : CY})`}>
      <circle r={40} className="game-core" />
      <text y={-3} textAnchor="middle" className="game-name">1 to 40</text>
      <text y={15} textAnchor="middle" className="game-sub">{hardened ? 'verified transfer' : 'Number hunt'}</text>
    </g>
  </svg>;
}

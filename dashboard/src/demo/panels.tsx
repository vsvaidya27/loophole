import { report, retrieval, sourceEvidence } from './transfer';
import { FAMILY, type DemoData } from './data';

export function Recall({ data, step }: { data: DemoData; step: number }) {
  const offered = new Set(data.retrieval.offered_to_prompt);
  const top = Math.max(...data.retrieval.matches.map(m => m.score));
  return <div className="panel-body">
    <div className="recall-stats">
      <div><strong>{data.graph_before.invariants.length}</strong><span>Hub invariants from {data.graph_before.environments.length} source environments</span></div>
      <div><strong>{data.retrieval.matches.length}</strong><span>candidates returned; one selected for adaptation</span></div>
    </div>
    {step >= 1 && <ol className="recall-list">
      {data.retrieval.matches.map((m, i) => <li key={m.id} className={step >= 2 && offered.has(m.id) ? 'handed' : undefined} style={{ animationDelay: `${i * 140}ms` }}>
        <span className="pick">{i + 1}</span>
        <div><b>{m.title}</b><small>{FAMILY[m.exploit_class] ?? m.exploit_class}, found in {m.env_id.startsWith('game/') ? 'a generated game' : m.env_id}</small></div>
        <span className="relevance" title={m.reasons.join('; ')}><i style={{ width: `${(m.score / top) * 100}%` }} /></span>
      <details className="rule-provenance"><summary>Where this rule came from{m.id === report.source.invariant_id ? ' · selected for transfer' : ''}</summary><p>{retrieval.matches.find(rule => rule.invariant_id === m.id)?.mechanism}</p><p><b>Reusable defense:</b> {m.defense}</p><code>{m.id}</code><a href={sourceEvidence(m.id)} target="_blank" rel="noreferrer">Open original audit evidence ↗</a></details>
      </li>)}
    </ol>}
    {step >= 2 && <p className="callout knowledge visible">Moss searched {data.retrieval.indexed} Hub invariants and returned five candidates. An operator selected rank two, Mini Sudoku, because its tagged-answer preconditions fit this target. Only that rule went to the adaptation call.</p>}
  </div>;
}

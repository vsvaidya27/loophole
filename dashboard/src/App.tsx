import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { buildGraph, type LiveSnapshot } from './live';
import { useLiveStore } from './hooks/useLiveStore';
import { ConnectionStatus } from './components/ConnectionStatus';
import { EvidenceInspector, type EvidenceTab } from './components/EvidenceInspector';
import { InvariantNetwork } from './components/InvariantNetwork';
import { AuditTable } from './components/AuditTable';
import type { GraphProjection } from './graph/buildGraph';

const emptyGraph: GraphProjection = { nodes: [], edges: [], diagnostics: [] };
const HubLeaderboard = lazy(() => import('./components/HubLeaderboard').then(module => ({ default: module.HubLeaderboard })));

function Metrics({ snapshot, graph }: { snapshot?: LiveSnapshot; graph: GraphProjection }) {
  const ids = new Set(snapshot?.rows.environments.map(env => env.envId));
  const metrics = snapshot ? [
    { value: ids.size, label: 'Environments', caption: 'Audited or generated tasks' },
    { value: snapshot.exploits.filter(row => ids.has(row.envId)).length, label: 'Recorded failures', caption: 'Stored exploit observations' },
    { value: snapshot.invariants.filter(row => ids.has(row.envId)).length, label: 'Extracted invariants', caption: 'Constraints derived from failures' },
    { value: graph.edges.filter(edge => edge.kind === 'applied_to').length, label: 'Transfer outcomes', caption: 'Includes unsuccessful tests' },
  ] : [];
  return <section className="metrics" id="metrics" aria-label="Knowledge store totals" aria-live="polite">
    {metrics.map(metric => <div key={metric.label} className="metric"><span>{metric.label}</span><strong>{metric.value}</strong><small>{metric.caption}</small></div>)}
  </section>;
}

export function App() {
  const [view, setView] = useState<'network' | 'leaderboard'>(() => window.location.hash === '#leaderboard' ? 'leaderboard' : 'network');
  const live = useLiveStore();
  const { snapshot, status } = live;
  const graph = useMemo(() => snapshot ? buildGraph(snapshot.rows) : emptyGraph, [snapshot]);
  const [selection, setSelection] = useState<{ id?: string; tab: EvidenceTab }>({ tab: 'failure' });
  const workspace = useRef<HTMLElement>(null);
  const selected = graph.nodes.some(node => node.id === selection.id) ? selection.id : undefined;
  const select = (id?: string, tab: EvidenceTab = 'failure') => setSelection({ id, tab });
  const navigate = (next: 'network' | 'leaderboard') => {
    setView(next);
    window.history.replaceState(null, '', next === 'leaderboard' ? '#leaderboard' : '#network');
  };
  useEffect(() => {
    const update = () => setView(window.location.hash === '#leaderboard' ? 'leaderboard' : 'network');
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  useEffect(() => {
    if (snapshot && selection.id && !selected) setSelection({ tab: 'failure' });
  }, [snapshot, selection.id, selected]);

  const environments = snapshot?.rows.environments ?? [];
  const calibrationCount = environments.filter(env => env.envId.startsWith('game/scripted-')).length;
  const pilotCount = environments.filter(env => env.envId.startsWith('game/ai-') || env.title.includes('model-generated')).length;
  const selectedInvariant = graph.nodes.find(node => node.id === selected && node.kind === 'invariant');
  const environmentFocus = selected?.startsWith('env:') ? selected : selectedInvariant?.kind === 'invariant' ? `env:${selectedInvariant.envId}` : '';
  const emptyMessage = snapshot
    ? 'Connected. No knowledge records have been published yet.'
    : status === 'error' || status === 'disconnected'
      ? 'The live store is unavailable. Reconnect to load its recorded audits.'
      : 'Waiting for the initial subscription…';

  return <main>
    <header className="page-header"><div><a className="wordmark" href="/" aria-label="Loophole home"><span aria-hidden="true">∞</span> loophole</a><h1>Reward integrity</h1></div><nav aria-label="Main navigation"><a aria-current={view === 'network' ? 'page' : undefined} href="#network" onClick={e => { e.preventDefault(); navigate('network'); }}>Knowledge graph</a><a aria-current={view === 'leaderboard' ? 'page' : undefined} href="#leaderboard" onClick={e => { e.preventDefault(); navigate('leaderboard'); }}>Hub leaderboard</a><a href="/replay.html">Game & training replays <span aria-hidden="true">↗</span></a></nav></header>
    <ConnectionStatus {...live} />
    {view === 'leaderboard' && <Suspense fallback={<p className="lb-no-results" role="status">Loading saved audit results…</p>}><HubLeaderboard snapshot={snapshot} onInspect={id => { select(id); navigate('network'); }} /></Suspense>}
    <div hidden={view !== 'network'}>
    <Metrics snapshot={snapshot} graph={graph} />
    <section className="workspace" ref={workspace}>
      <div className="graph-panel">
        <div className="toolbar">
          <div><div className="eyebrow">ENVIRONMENTS / FAILURES / CONSTRAINTS</div><h2>The invariant network</h2></div>
          <div className="graph-focus"><label htmlFor="environment-focus">Inspect an environment</label>
            <select id="environment-focus" value={environmentFocus} onChange={event => select(event.target.value || undefined)}>
              <option value="">Entire knowledge store</option>{environments.map(env => <option key={env.envId} value={`env:${env.envId}`}>{env.title}</option>)}
            </select>
          </div>
          <button id="clear-selection" onClick={() => select()}>Reset focus</button>
        </div>
        <p id="scope" className="scope">{snapshot && `${environments.length} environments · ${calibrationCount} scripted calibrations · ${pilotCount} model-generated pilot${pilotCount === 1 ? '' : 's'}. Selection highlights connections; the entire store stays visible.`}</p>
        <div className="network-legend"><span><i className="env-dot" /> Environment</span><span><i className="inv-dot" /> Invariant</span><span><i className="rule-dot" /> Rule family</span><span><i className="source-line" /> Found in</span><span><i className="transfer-line" /> Transfer test</span><span><i className="similarity-line" /> Similarity</span></div>
        <p id="empty" role="status" hidden={graph.nodes.length > 0}>{graph.nodes.length ? '' : emptyMessage}</p>
        <InvariantNetwork graph={graph} selected={selected} onSelect={id => select(selected === id ? undefined : id)} />
        <p id="diagnostics">{graph.diagnostics.length > 0 && `${graph.diagnostics.length} incomplete or invalid references. Some tables may still be arriving.`}</p>
        <details className="graph-explainer"><summary>What the connections mean</summary><p>Each large hub is an environment. Its colored satellites are invariant records extracted from reward failures; satellite colors identify failure classes. Violet diamond nodes connect shared rule families below the environment hubs.</p><p>Solid lines show where a failure was found. Dashed arrows show recorded transfer tests; inspect their outcomes before treating them as successful defenses. Dotted lines show similarity, which alone does not establish transfer.</p></details>
        <div className="invariant-key" id="invariant-key" aria-label="Invariant records">
          {graph.nodes.filter(node => node.kind === 'invariant').map((node, index) => <button key={node.id} className={selected === node.id ? 'active' : undefined} aria-pressed={selected === node.id} onClick={() => select(node.id)}>I{index + 1}  {node.label}</button>)}
        </div>
      </div>
      <EvidenceInspector key={selected ?? 'empty'} snapshot={snapshot} selected={selected} activeTab={selection.tab} onTab={tab => setSelection(previous => ({ ...previous, tab }))} onSelect={select} />
    </section>
    <AuditTable snapshot={snapshot} onSelect={id => { select(id); workspace.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }} />
    </div>
    <footer><span>Loophole · Compile environments. Check rewards. Measure learning.</span><a href="/replay.html">Compare recorded policies <span aria-hidden="true">→</span></a></footer>
  </main>;
}

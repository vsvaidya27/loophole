import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import type { LiveSnapshot } from '../live';
import { humanize, provenance, score } from '../format';

export type EvidenceTab = 'failure' | 'defense' | 'transfer';
export type SelectRecord = (id?: string, tab?: EvidenceTab) => void;
type Props = {
  snapshot?: LiveSnapshot;
  selected?: string;
  activeTab: EvidenceTab;
  onTab: (tab: EvidenceTab) => void;
  onSelect: SelectRecord;
};

function Section({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return <section className={`evidence-section ${className}`}><h4>{title}</h4><p>{children || 'Not included in this record.'}</p></section>;
}

function ReplayEvidence({ value }: { value: string }) {
  let formatted = value;
  try { formatted = JSON.stringify(JSON.parse(value), null, 2); } catch { /* Recorded evidence may be plain text. */ }
  return <details className="raw-evidence"><summary>Replay evidence</summary><pre>{formatted || 'No payload attached.'}</pre></details>;
}

function RecordButton({ id, children, onSelect, tab }: { id: string; children: ReactNode; onSelect: SelectRecord; tab?: EvidenceTab }) {
  return <button className="evidence-link" onClick={() => onSelect(id, tab)}>{children}</button>;
}

function InvariantEvidence({ snapshot, selected, activeTab, onTab, onSelect }: Props & { snapshot: LiveSnapshot; selected: string }) {
  const buttons = useRef<Partial<Record<EvidenceTab, HTMLButtonElement>>>({});
  const id = selected.slice(4);
  const inv = snapshot.invariants.find(row => row.invariantId === id);
  const exploit = snapshot.exploits.find(row => row.invariantId === id);
  const env = snapshot.rows.environments.find(row => row.envId === (inv?.envId ?? exploit?.envId));
  const attempts = snapshot.applications.filter(row => row.invariantId === id && row.targetEnvId !== (inv?.envId ?? exploit?.envId));
  const tabs: EvidenceTab[] = ['failure', 'defense', 'transfer'];
  const activate = (tab: EvidenceTab) => { onTab(tab); buttons.current[tab]?.focus(); };
  const navigate = (event: KeyboardEvent<HTMLButtonElement>, tab: EvidenceTab) => {
    let next: EvidenceTab | undefined;
    if (event.key === 'ArrowRight') next = tabs[(tabs.indexOf(tab) + 1) % tabs.length];
    if (event.key === 'ArrowLeft') next = tabs[(tabs.indexOf(tab) + tabs.length - 1) % tabs.length];
    if (event.key === 'Home') next = 'failure';
    if (event.key === 'End') next = 'transfer';
    if (next) { event.preventDefault(); activate(next); }
  };

  return <>
    <span className="provenance-badge">{provenance(env)}</span>
    <h3 className="inspector-title">{inv?.title ?? exploit?.summary ?? 'Extraction pending'}</h3>
    <div className="evidence-tabs" role="tablist" aria-label="Evidence sections">
      {tabs.map(tab => <button key={tab} ref={node => { if (node) buttons.current[tab] = node; else delete buttons.current[tab]; }}
        id={`tab-${tab}`} role="tab" aria-selected={activeTab === tab} aria-controls="evidence-content" tabIndex={activeTab === tab ? 0 : -1}
        onClick={() => activate(tab)} onKeyDown={event => navigate(event, tab)}>
        {tab === 'transfer' ? `Transfer (${attempts.length})` : tab === 'failure' ? 'Failure' : 'Defense'}
      </button>)}
    </div>
    <div className="evidence-content" id="evidence-content" role="tabpanel" aria-labelledby={`tab-${activeTab}`} tabIndex={0}>
      {activeTab === 'failure' && <>
        <div className="reward-comparison">
          {[{ title: 'Reward awarded', value: exploit?.rewardOriginal, tone: 'original' }, { title: 'After repair', value: exploit?.rewardPatched, tone: 'patched' }].map(item =>
            <div key={item.tone} className={item.tone}><span>{item.title}</span><strong className={score(item.value) === 'Not recorded' ? 'unmeasured' : undefined}>{score(item.value)}</strong></div>)}
        </div>
        {exploit && <p className="record-status"><span>Recorded status</span><strong>{humanize(exploit.status)}</strong></p>}
        <Section title="Task under audit">{env?.title ?? 'Environment record pending.'}</Section>
        <section className="evidence-section"><h4>Submitted answer</h4><pre>{exploit?.sampleCompletion || 'No completion attached.'}</pre></section>
        <Section title="How it earned reward">{inv?.mechanism ?? exploit?.summary ?? 'Invariant extraction has not arrived.'}</Section>
        <div className="evidence-note"><strong>Reward is not a correctness verdict.</strong><p>The scores above are grader outputs. Inspect the run’s replay evidence for the correctness check.</p></div>
      </>}
      {activeTab === 'defense' && <>
        <Section title="Constraint to enforce" className="defense-pattern">{inv?.defensePattern ?? 'Invariant extraction pending.'}</Section>
        <Section title="Root cause">{inv?.rootCause}</Section>
        <Section title="Applies when">{inv?.preconditions}</Section>
        <Section title="Recorded re-score">{exploit?.rewardPatched === undefined ? 'No patched reward has been published for this failure.' : `This completion earned ${score(exploit.rewardOriginal)} before repair and ${score(exploit.rewardPatched)} after repair.`}</Section>
        <Section title="Benign-answer checks">Pass counts are not included in this graph feed. Consult the run evidence before concluding that the repair preserves valid answers.</Section>
      </>}
      {activeTab === 'transfer' && <>
        {!attempts.length && <Section title="No transfer test recorded">Related invariants suggest where to look. They do not establish that a defense works in another environment.</Section>}
        {attempts.map(attempt => {
          const target = snapshot.rows.environments.find(row => row.envId === attempt.targetEnvId);
          return <article className="transfer-card" key={attempt.applicationKey}>
            <span className={`outcome ${attempt.outcome === 'blocked' ? 'blocked' : 'other'}`}>{humanize(attempt.outcome)}</span>
            <h4>{target?.title ?? attempt.targetEnvId}</h4>
            <p className="transfer-meta">{provenance(target)} · {attempt.runId}</p>
            <ReplayEvidence value={attempt.detail} />
            {target && <RecordButton id={`env:${target.envId}`} onSelect={onSelect}>Inspect target environment →</RecordButton>}
          </article>;
        })}
      </>}
    </div>
    <div className="evidence-source"><span>Evidence path</span><code>{inv?.evidencePath || exploit?.evidencePath || 'No evidence path attached.'}</code></div>
  </>;
}

function RecordEvidence(props: Props) {
  const { snapshot, selected, onSelect } = props;
  if (!snapshot || !selected) {
    const first = snapshot?.invariants.find(row => row.envId.includes('/ai-')) ?? snapshot?.invariants[0];
    return <>
      <div className="inspector-empty-mark">↗</div><h3 className="inspector-title">Follow one reward failure.</h3>
      <p className="inspector-intro">Choose a satellite to inspect the submitted answer, recorded reward, and constraint extracted from the failure.</p>
      <ol className="inspector-steps">
        <li><strong>Inspect the failure</strong><p>What earned reward, and why?</p></li>
        <li><strong>Review the defense</strong><p>What changed in the grader?</p></li>
        <li><strong>Check transfer</strong><p>Was the rule tested in another environment?</p></li>
      </ol>
      {first && <RecordButton id={`inv:${first.invariantId}`} onSelect={onSelect}>Inspect a recorded failure →</RecordButton>}
    </>;
  }
  if (selected.startsWith('inv:')) return <InvariantEvidence {...props} snapshot={snapshot} selected={selected} />;
  if (selected.startsWith('env:')) {
    const env = snapshot.rows.environments.find(row => row.envId === selected.slice(4));
    if (!env) return null;
    const members = snapshot.invariants.filter(row => row.envId === env.envId);
    const transfers = snapshot.applications.filter(row => row.targetEnvId === env.envId && snapshot.invariants.some(inv => inv.invariantId === row.invariantId && inv.envId !== env.envId));
    return <>
      <span className="provenance-badge">{provenance(env)}</span><h3 className="inspector-title">{env.title}</h3>
      <Section title="Audit status">{humanize(env.status)}</Section>
      <h4 className="list-heading">{members.length} extracted invariant{members.length === 1 ? '' : 's'}</h4>
      {members.map(inv => <RecordButton key={inv.invariantId} id={`inv:${inv.invariantId}`} onSelect={onSelect}>{inv.title}</RecordButton>)}
      {!members.length && <p className="inspector-intro">No extracted invariant records have arrived for this environment.</p>}
      {transfers.length > 0 && <h4 className="list-heading">Rules tested here</h4>}
      {transfers.map(attempt => <RecordButton key={attempt.applicationKey} id={`inv:${attempt.invariantId}`} tab="transfer" onSelect={onSelect}>
        {humanize(attempt.outcome)} · {snapshot.invariants.find(inv => inv.invariantId === attempt.invariantId)?.title ?? attempt.invariantId}
      </RecordButton>)}
    </>;
  }
  const rule = snapshot.rows.rules.find(row => row.ruleId === selected.slice(5));
  if (!rule) return null;
  return <>
    <h3 className="inspector-title">{rule.title}</h3>
    <p className="inspector-intro">{rule.memberCount} invariant records across {rule.envCount} environments.</p>
    <Section title="Shared failure class">These observations are grouped by mechanism. Open an invariant to inspect its preconditions and recorded transfer outcomes.</Section>
    {snapshot.invariants.filter(inv => inv.exploitClass === rule.ruleId).map(inv => <RecordButton key={inv.invariantId} id={`inv:${inv.invariantId}`} onSelect={onSelect}>{inv.title}</RecordButton>)}
  </>;
}

export function EvidenceInspector(props: Props) {
  const { selected } = props;
  const kind = selected?.startsWith('inv:') ? 'Invariant' : selected?.startsWith('env:') ? 'Environment' : selected ? 'Rule family' : 'No selection';
  return <aside className="evidence-panel" aria-label="Selected record evidence">
    <div className="inspector-heading"><span className="eyebrow">EVIDENCE INSPECTOR</span><span id="selection-kind">{kind}</span></div>
    <div id="details"><RecordEvidence {...props} />{selected && <p className="record-id">{selected}</p>}</div>
  </aside>;
}

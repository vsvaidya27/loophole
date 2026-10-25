import { Fragment, useMemo, useState } from 'react';
import type { LiveSnapshot } from '../live';
import { evidenceUrl, leaderboard, percent, sortEntries, statusLabels, summarize, type AuditEntry, type SortOrder } from '../leaderboard';
import { humanize } from '../format';

function AttackRate({ entry }: { entry: AuditEntry }) {
  if (entry.asrBefore === null || entry.asrAfter === null) return <span className="lb-unmeasured">Not measured</span>;
  return <div className="lb-rate" aria-label={`Attack success ${percent(entry.asrBefore)} before, ${percent(entry.asrAfter)} after`}>
    <div><span>{percent(entry.asrBefore)}</span><span className="lb-arrow" aria-hidden="true">→</span><strong>{percent(entry.asrAfter)}</strong></div>
    <div className="lb-rate-bars" aria-hidden="true"><i style={{ width: `${entry.asrBefore * 100}%` }} /><i style={{ width: `${entry.asrAfter * 100}%` }} /></div>
  </div>;
}

function AuditEvidence({ entry, inGraph, onInspect }: { entry: AuditEntry; inGraph: boolean; onInspect: (id: string) => void }) {
  const [findingId, setFindingId] = useState(entry.findings[0]?.id ?? '');
  const finding = entry.findings.find(f => f.id === findingId);
  return <div className="lb-evidence">
    <div className="lb-evidence-head"><div><div className="eyebrow">RECORDED AUDIT / {entry.publisher}</div><h3>{entry.name}</h3></div>
      <div className="lb-evidence-actions">
        <a href={evidenceUrl(entry.status === 'failed_to_run' ? `${entry.evidenceDir}/install.log` : `${entry.evidenceDir}/summary.json`)} target="_blank" rel="noreferrer">Run evidence ↗</a>
        <button disabled={!inGraph} onClick={() => onInspect(`env:${entry.envId}`)}>{inGraph ? 'Inspect in knowledge graph →' : 'Not in current graph feed'}</button>
      </div>
    </div>
    {entry.failureReason && <p className="lb-outcome-note">This environment could not be scored. No attack or repair rate is reported.<br />{entry.failureReason}</p>}
    {entry.status === 'robust' && <p className="lb-outcome-note">No confirmed false positive in {entry.probes} submitted probes. This is a sampled outcome; no repair was needed in this run.</p>}
    {entry.status === 'unpatched' && <div className="lb-outcome-note"><strong>No repair met the acceptance gates.</strong><p>{entry.unpatchedReasons.join(' · ') || entry.stopReason}</p><p>Defense patterns below are proposed constraints; they have no accepted repaired reward in this run.</p></div>}
    {finding && <>
      <label className="lb-finding-picker">Recorded finding
        <select value={findingId} onChange={event => setFindingId(event.target.value)}>
          {entry.findings.map(f => <option key={f.id} value={f.id}>{f.title}</option>)}
        </select>
      </label>
      <div className="lb-evidence-grid">
        <section><span className="lb-class">{humanize(finding.exploitClass)}</span><h4>{finding.title}</h4><p>{finding.mechanism}</p>
          <h4>Applies when</h4><p>{finding.preconditions}</p>
          <h4>{finding.closed ? 'Defense pattern' : 'Proposed defense pattern'}</h4><p>{finding.defense}</p>
        </section>
        <section><div className="lb-evidence-scores"><span>Recorded reward <strong>{finding.originalReward.toFixed(3)} <span aria-hidden="true">→</span> {finding.patchedReward === null ? 'Not patched' : finding.patchedReward.toFixed(3)}</strong></span><span>Independent verdict <strong>{finding.verdict}</strong></span></div>
          <h4>Submitted answer</h4><pre>{finding.submittedAnswer}</pre>
          <details><summary>Reference answer and verdict</summary><pre>{finding.referenceAnswer}</pre><p>{finding.verdictReason}</p></details>
          <a className="lb-replay-link" href={evidenceUrl(finding.evidencePath)} target="_blank" rel="noreferrer">Open saved replay ↗</a>
        </section>
      </div>
    </>}
    <p className="lb-sample-note">{entry.probes} submitted probes · {entry.benignCases} distinct valid-answer checks · {entry.rounds} audit rounds · ${entry.costUsd.toFixed(4)} recorded API spend. Findings count saved exploit records, which can include related variants.</p>
  </div>;
}

export function HubLeaderboard({ snapshot, onInspect }: { snapshot?: LiveSnapshot; onInspect: (id: string) => void }) {
  const [search, setSearch] = useState('');
  const [scope, setScope] = useState('all');
  const [outcome, setOutcome] = useState('all');
  const [order, setOrder] = useState<SortOrder>('closed');
  const [expanded, setExpanded] = useState<string>();
  const scoped = useMemo(() => leaderboard.entries.filter(e => scope === 'all' || e.publisher === 'primeintellect'), [scope]);
  const totals = summarize(scoped);
  const rows = useMemo(() => sortEntries(scoped.filter(e => (outcome === 'all' || e.status === outcome)
    && `${e.envId} ${e.classes.join(' ')}`.toLowerCase().includes(search.trim().toLowerCase())), order), [scoped, search, outcome, order]);
  const hostedIds = new Set(snapshot?.rows.environments.map(e => e.envId));
  const primeCount = leaderboard.entries.filter(e => e.publisher === 'primeintellect').length;

  return <section className="hub-leaderboard" aria-labelledby="leaderboard-title">
    <div className="lb-heading"><div><div className="eyebrow">PRIME INTELLECT HUB / AUDIT RESULTS</div><h2 id="leaderboard-title">Can the reward be trusted?</h2><p>We audited open-source RL environments, reproduced false rewards, and measured what the repairs preserved.</p></div><span className="lb-snapshot-badge">Recorded experiment <span>Oct 24, 2026</span></span></div>
    <div className="lb-summary" aria-label="Audit experiment totals">
      <div><span>Hub environments</span><strong>{totals.environments}</strong><small>{totals.loaded} loaded · {totals.environments - totals.loaded} could not run</small></div>
      <div><span>Confirmed findings</span><strong className="lb-amber">{totals.findings}</strong><small>Independently incorrect, yet rewarded</small></div>
      <div><span>Findings closed</span><strong className="lb-mint">{totals.closed}<em> / {totals.findings}</em></strong><small>{totals.open} remain open</small></div>
      <div><span>Environments repaired</span><strong>{totals.repaired}</strong><small>Accepted attack and valid-answer gates</small></div>
    </div>
    <div className="lb-panel">
      <div className="lb-controls">
        <label className="lb-search"><span className="eyebrow">FIND AN ENVIRONMENT</span><input type="search" placeholder="Name, publisher, or failure class…" value={search} onChange={e => setSearch(e.target.value)} /></label>
        <label>Scope<select value={scope} onChange={e => setScope(e.target.value)}><option value="all">All Hub publishers ({leaderboard.entries.length})</option><option value="primeintellect">Prime Intellect publisher ({primeCount})</option></select></label>
        <label>Outcome<select value={outcome} onChange={e => setOutcome(e.target.value)}><option value="all">All outcomes</option>{Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>Order by<select value={order} onChange={e => setOrder(e.target.value as SortOrder)}><option value="closed">Most findings closed</option><option value="findings">Most findings discovered</option><option value="asr">Largest attack-rate reduction</option><option value="name">Environment name</option></select></label>
      </div>
      <div className="lb-table-caption"><span>{rows.length} of {scoped.length} environments · {totals.probes} probes in this scope</span><span>Sampled audit outcomes · lower attack success is better</span></div>
      <div className="table-scroll"><table className="lb-table">
        <caption className="sr-only">Prime Intellect Hub auditing leaderboard. Default order is findings closed. Missing measurements are not zero.</caption>
        <thead><tr><th scope="col">#</th><th scope="col">Environment</th><th scope="col">Audit outcome</th><th scope="col">Findings <span>found / closed</span></th><th scope="col">Attack success <span>before → after</span></th><th scope="col">Valid answers <span>pass rate after</span></th><th scope="col">Rounds</th><th scope="col">API spend</th><th scope="col">Evidence</th></tr></thead>
        <tbody>{rows.map((entry, index) => <Fragment key={entry.envId}>
          <tr className={expanded === entry.envId ? 'lb-expanded-row' : undefined}>
            <td className="lb-rank">{index + 1}</td><td><strong className="lb-env-name">{entry.name}</strong><small className="lb-publisher">{entry.publisher}</small></td>
            <td><span className={`lb-status ${entry.status}`}>{statusLabels[entry.status]}</span></td>
            <td>{entry.status === 'failed_to_run' ? <span className="lb-unmeasured">Not measured</span> : <><strong className="lb-findings">{entry.findings.length} <span>/</span> <span className="lb-mint">{entry.closed}</span></strong>{entry.open > 0 && <small className="lb-open">{entry.open} open</small>}</>}</td>
            <td><AttackRate entry={entry} /></td><td><strong className={entry.benignAfter === null ? 'lb-unmeasured' : 'lb-valid'}>{entry.benignAfter === null ? 'Not measured' : percent(entry.benignAfter)}</strong></td>
            <td className="lb-numeric">{entry.rounds}</td><td className="lb-numeric">${entry.costUsd.toFixed(2)}</td>
            <td><button className="lb-expand" aria-expanded={expanded === entry.envId} aria-controls={`audit-detail-${index}`} onClick={() => setExpanded(expanded === entry.envId ? undefined : entry.envId)}>{expanded === entry.envId ? 'Close −' : 'Inspect ↗'}</button></td>
          </tr>
          {expanded === entry.envId && <tr id={`audit-detail-${index}`}><td colSpan={9} className="lb-detail-cell"><AuditEvidence entry={entry} inGraph={hostedIds.has(entry.envId)} onInspect={onInspect} /></td></tr>}
        </Fragment>)}</tbody>
      </table></div>
      {!rows.length && <p className="lb-no-results" role="status">No environments match these filters.</p>}
    </div>
    <div className="lb-methodology">
      <section><span>01 / FIND</span><h3>A reward failure, not just a weird answer.</h3><p>A confirmed finding earned high reward while an independent correctness check marked it incorrect. Several records may be variants of one mechanism.</p></section>
      <section><span>02 / REPAIR</span><h3>Block the attack. Keep valid answers.</h3><p>Attack success is the share of submitted probes that are incorrect and still score at least 80% of the reference reward. Valid-answer pass rate measures the separate benign set.</p></section>
      <section><span>03 / EXPLAIN</span><h3>Evidence behind every result.</h3><p>Inspect each record for its answer, verdict, reward and defense. The graph shows shared patterns; transfer success requires a separate target-specific test.</p></section>
    </div>
    <div className="lb-provenance"><p>Saved audit snapshot · {leaderboard.auditDate} · {leaderboard.source.protocol} This is Loophole’s audit of Hub environments, not an official Prime Intellect model ranking or a whole-dataset security guarantee. Sorting changes the display order, not an overall security score. Snapshot metrics do not change when graph records are updated.</p><div><a href={evidenceUrl(leaderboard.source.path)} target="_blank" rel="noreferrer">Source leaderboard ↗</a><a href={evidenceUrl(leaderboard.source.checkerLog)} target="_blank" rel="noreferrer">Saved acceptance-check log ↗</a></div></div>
  </section>;
}

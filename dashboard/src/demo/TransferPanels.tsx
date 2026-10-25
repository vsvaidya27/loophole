import { useState } from 'react';
import { report, EVIDENCE_ROOT, sourceEvidence } from './transfer';

export function TransferGame({ flaw }: { flaw: boolean }) {
  return <div className="panel-body">
    <p className="game-rules">Find a hidden number from 1 to 40. Receive higher/lower feedback after each guess, with up to seven turns.</p>
    <p className="fine">Target: <code>{report.targetRef}</code>, an existing compiler-library environment. This experiment did not generate a new game.</p>
    {flaw && <p className="callout loophole visible">The loose grader counts every numeric candidate. Listing all forty numbers earns reward without finding a single committed answer.</p>}
    <p className="fine">An invariant is a condition that must remain true for fair scoring. Here: each reply must commit to one unambiguous guess.</p>
  </div>;
}

export function TransferAttack({ summary }: { summary: boolean }) {
  const v = report.validation;
  return <div className="panel-body">
    <figure className="code-card"><figcaption>Recorded scripted attack, not a new model discovery</figcaption><pre>{v.attackExample.replies[0]}</pre></figure>
    <div className="recall-stats"><div><strong>{v.rewardBefore.toFixed(1)}</strong><span>original grader reward</span></div><div><strong>{v.attackExample.strict.toFixed(1)}</strong><span>strict target oracle</span></div></div>
    <p className="callout loophole visible">The grader pays for a reply that fails the single-answer requirement.</p>
    {summary && <p className="fine">Validation covers {v.attackVariants} scripted variants across {v.seeds} seeds: {v.attackCases} cases, not {v.attackCases} independently discovered exploits. The adaptation model did not see these cases.</p>}
  </div>;
}

export function TransferPatch({ checked }: { checked: boolean }) {
  const v = report.validation;
  return <div className="panel-body">
    <p className="rule-plain">Mini Sudoku → reject conflicting answer blocks → one tagged integer per turn.</p>
    <p className="fine">One Haiku call adapted the selected rule. The rule only lowers reward and reads no hidden state.</p>
    <figure className="code-card patch"><figcaption>The actual saved adaptation</figcaption><pre>{report.adaptation.code}</pre></figure>
    {checked && <><ul className="checks"><li>{v.blocked}/{v.attackCases} scripted attack cases blocked</li><li>{v.benignPassed}/{v.benignTotal} reference and harmless-preface cases preserved</li><li>{v.gates}</li></ul><p className="fine">Static checks followed by OS-sandbox validation with no network or API keys.</p></>}
  </div>;
}

export function TransferResult({ details }: { details: boolean }) {
  const [turn, setTurn] = useState(2);
  const v = report.validation;
  const maxTurn = (v.referenceTranscript.length - 1) / 2;
  return <div className="panel-body">
    <p className="callout knowledge visible">{v.blocked}/{v.attackCases} attack cases: reward 1 → 0. {v.benignPassed}/{v.benignTotal} valid cases: reward 1 → 1. Reference games still take 2–6 turns.</p>
    <div className="transfer-recorded"><h3>A valid recorded episode</h3><ol>{v.referenceTranscript.slice(0, 1 + 2 * turn).map(([who, text], i) => <li key={i}><b>{who === 'agent' ? 'Player' : 'Environment'}</b><p>{text}</p></li>)}</ol><div className="transport"><button disabled={!turn} onClick={() => setTurn(t => t - 1)}>Previous turn</button><span>{turn}/{maxTurn}</span><button disabled={turn === maxTurn} onClick={() => setTurn(t => t + 1)}>Next turn</button></div></div>
    {details && <><div className="ticker"><div><strong>{report.modelCalls}</strong><span>Haiku adaptation call</span></div><div><strong>${report.modelSpendUsd.toFixed(5)}</strong><span>recorded model cost</span></div></div>
    <p className="fine">Published: one target environment and one blocked rule-application edge from the existing Mini Sudoku invariant. No new invariant was created by this transfer.</p>
    <p className="fine">One measured transfer, with operator selection and a planted parser flaw. No retrieval-efficiency improvement or exhaustive security guarantee is established.</p></>}
    <div className="transfer-links"><a href={sourceEvidence(report.source.invariant_id)} target="_blank" rel="noreferrer">Source audit evidence ↗</a><a href={`${EVIDENCE_ROOT}graph_transfer/${report.runId}/report.json`} target="_blank" rel="noreferrer">Full recorded validation ↗</a><a href={`${EVIDENCE_ROOT}graph_transfer/${report.runId}/publication.json`} target="_blank" rel="noreferrer">Graph publication ↗</a></div>
  </div>;
}

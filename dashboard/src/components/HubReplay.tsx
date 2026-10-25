import { useEffect, useRef, useState } from 'react';
import { evidenceUrl } from '../leaderboard';
import '../hubReplay.css';

type DemoCase = { id: string; label: string; exampleIndex: number; digest: string; messages: { role: string; content: string }[];
  gold: string; completion: string; reference: string; verdict: string; verdictReason: string; evidencePath: string };
type Demo = { environment: string; cases: DemoCase[]; patchPath: string; patchSha256: string; nativeTurns: string };
type ModeScore = { reward: number; referenceReward: number; elapsedMs: number; runtimeFingerprint: string; distributions: string[] };
type Comparison = { caseId: string; mode: string; scoredAt: string; scores: { original: ModeScore; hardened: ModeScore };
  exampleDigest: string; patchSha256: string; elapsedMs: number; verdict: string; verdictSource: string; modelCalls: number };

function GraderPanel({ hardened, result, busy, blocks, gold }: { hardened: boolean; result?: ModeScore; busy: boolean; blocks: string[]; gold: string }) {
  return <section className={`hub-grader ${hardened ? 'hardened' : 'original'}`}>
    <div className="hub-grader-heading"><div className="eyebrow">{hardened ? 'AFTER HARDENING' : 'BEFORE HARDENING'}</div><h3>{hardened ? 'Accepted repair' : 'Original Hub environment'}</h3></div>
    <div className="hub-live-score" aria-live="polite"><strong>{busy ? '…' : result ? result.reward.toFixed(3) : '—'}</strong><span>{busy ? 'Scoring locally…' : result ? 'Freshly measured reward' : 'Run comparison to measure'}</span></div>
    <div className="hub-parser-rule"><span>{hardened ? 'Constraint applied' : 'Original reward behavior'}</span><p>{hardened ? 'Every answer block must exactly match the reference. Conflicting blocks or a near-match earn zero.' : 'The parser takes the first answer block. Similarity to the reference determines its reward.'}</p></div>
    <h4>Answer blocks visible in the response</h4>
    <div className="hub-blocks">{blocks.map((block, index) => <div className={`${hardened || index === 0 ? 'considered' : 'ignored'} ${block.trim().normalize('NFC') === gold.trim().normalize('NFC') ? 'matches' : 'differs'}`} key={index}>
      <span>BLOCK {index + 1} · {block.trim().normalize('NFC') === gold.trim().normalize('NFC') ? 'matches reference' : 'differs from reference'}{!hardened && index > 0 ? ' · not selected by original parser' : ''}</span><pre>{block}</pre>
    </div>)}</div>
    <div className="hub-control-result"><span>Correct-answer control</span><strong>{result ? result.referenceReward.toFixed(3) : 'Not measured'}</strong></div>
    {result && <p className="hub-score-timing">{(result.elapsedMs / 1000).toFixed(2)}s · installed grader, cached dataset</p>}
  </section>;
}

export function HubReplay({ onInspect }: { onInspect: (id: string) => void }) {
  const [demo, setDemo] = useState<Demo>();
  const [caseId, setCaseId] = useState('');
  const [comparison, setComparison] = useState<Comparison>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const request = useRef<AbortController | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    fetch('/api/hub-demo', { signal: controller.signal }).then(async response => {
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('The local replay service is unavailable.');
      const value = await response.json() as Demo;
      if (value.environment !== 'primeintellect/reverse-text' || !value.cases?.length) throw new Error('Invalid replay service response.');
      setDemo(value); setCaseId(value.cases[0].id);
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => { controller.abort(); request.current?.abort(); };
  }, [reload]);
  const current = demo?.cases.find(c => c.id === caseId);
  const blocks = Array.from((current?.completion ?? '').matchAll(/<reversed_text>\s*([\s\S]*?)\s*<\/reversed_text>/g), match => match[1]);
  const controlPreserved = comparison && comparison.scores.hardened.referenceReward >= .8 * comparison.scores.original.referenceReward;
  const run = async () => {
    if (!current || busy) return;
    const controller = new AbortController(); request.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 75000);
    setBusy(true); setError(''); setComparison(undefined);
    try {
      const response = await fetch('/api/hub-demo/score', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ caseId }), signal: controller.signal });
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The local replay service is unavailable. No scores were substituted.');
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Live scoring failed.');
      if (result.caseId !== caseId || result.exampleDigest !== current.digest || result.patchSha256 !== demo?.patchSha256
        || ![result.scores?.original?.reward, result.scores?.hardened?.reward, result.scores?.original?.referenceReward, result.scores?.hardened?.referenceReward].every(Number.isFinite)) {
        throw new Error('Case, dataset, patch or score validation failed.');
      }
      setComparison(result);
    } catch (err) {
      setError(controller.signal.aborted ? 'The comparison was cancelled or timed out. No scores were substituted.' : (err as Error).message);
    } finally { window.clearTimeout(timeout); setBusy(false); }
  };
  return <section className="hub-replay" aria-labelledby="hub-replay-title">
    <div className="lb-heading"><div><div className="eyebrow">PRIME INTELLECT / REVERSE-TEXT</div><h2 id="hub-replay-title">Same response. Different reward.</h2><p>Replay a real saved interaction against the original environment and its accepted repair. Both rewards are computed when you click Run.</p></div><span className="lb-snapshot-badge">{demo ? 'Replay service connected' : 'Connecting to local scorer'}<span>CPU scoring · no model calls</span></span></div>
    <div className="hub-demo-controls"><div className="hub-case-buttons" aria-label="Recorded interaction">{demo?.cases.map(c => <button key={c.id} aria-pressed={caseId === c.id} disabled={busy} onClick={() => { setCaseId(c.id); setComparison(undefined); setError(''); }}>{c.label}</button>)}</div><button className="hub-run" disabled={!current || busy} onClick={run}>{busy ? 'Scoring both graders…' : 'Run live comparison →'}</button></div>
    {error && <div className="hub-demo-error" role="alert"><strong>{error}</strong>{!demo && <><p>Start the local scorer from the repository root:</p><pre>.venvs/hub/bin/python -m harden.experiments.hub_demo</pre><button onClick={() => setReload(value => value + 1)}>Reconnect scorer</button></>}</div>}
    {current && <>
      <div className="hub-interaction"><div className="hub-task"><span className="eyebrow">01 / ENVIRONMENT PROMPT</span><h3>Reverse every character. Return the result in tags.</h3><p>{current.messages.filter(m => m.role === 'user').map(m => m.content).join('\n')}</p><small>Dataset example #{current.exampleIndex} · native single-turn task</small></div>
        <div className="hub-response"><span className="eyebrow">02 / SAVED ASSISTANT RESPONSE</span><pre>{current.completion}</pre><span className={`hub-verdict ${current.verdict}`}><i />Saved correctness verdict: {current.verdict}</span></div></div>
      <div className="hub-grading-caption"><span className="eyebrow">03 / LIVE GRADER COMPARISON</span><p>The exact same response and dataset row go to both graders. The correct reference is also scored in both as a control.</p></div>
      <div className="hub-grader-grid"><GraderPanel hardened={false} result={comparison?.scores.original} busy={busy} blocks={blocks} gold={current.gold} /><GraderPanel hardened result={comparison?.scores.hardened} busy={busy} blocks={blocks} gold={current.gold} /></div>
      {comparison && <div className="hub-comparison-result" role="status"><strong>{current.verdict === 'correct' && controlPreserved && comparison.scores.hardened.reward >= .8 * comparison.scores.original.referenceReward ? 'Correct response retains credit.' : current.verdict !== 'correct' && controlPreserved && comparison.scores.original.reward >= .8 * comparison.scores.original.referenceReward && comparison.scores.hardened.reward === 0 ? 'False reward removed. Correct-answer control preserved.' : 'Measured result returned — inspect both scores.'}</strong><p>Scored {new Date(comparison.scoredAt).toLocaleTimeString()} · {(comparison.elapsedMs / 1000).toFixed(2)}s · dataset digest verified · {comparison.modelCalls} model calls</p></div>}
      <div className="hub-replay-links"><a href={evidenceUrl(current.evidencePath)} target="_blank" rel="noreferrer">Recorded interaction ↗</a><a href={evidenceUrl(demo!.patchPath)} target="_blank" rel="noreferrer">Accepted repair source ↗</a><button onClick={() => onInspect('env:primeintellect/reverse-text')}>See shared rules in the graph →</button></div>
      <details className="hub-provenance"><summary>What is live, and what is recorded?</summary><p>The task, assistant response, and independent correctness verdict come from the saved audit. The Run button starts fresh local scoring workers using the installed Hub package, cached dataset, and accepted Python repair. There is no new model generation, GPU training, or graph write. The diagram of answer blocks explains the recorded parser behavior; the numerical rewards come from Python, not browser simulation.</p><p>Patch SHA-256: <code>{demo?.patchSha256}</code></p>{comparison && <p>Dataset digest: <code>{comparison.exampleDigest}</code></p>}</details>
    </>}
  </section>;
}

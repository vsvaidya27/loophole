import { useRef, useState, useEffect } from 'react';
import evidence from '../data/graphTransferDemo.json';
import '../hubReplay.css';
import '../graphTransfer.css';

type Replay = { runId: string; moduleSha256: string; checkedAt: string; modelCalls: number; elapsedMs: number;
  validation: typeof evidence.validation };

export function GraphTransferDemo({ onInspect }: { onInspect: (id: string, tab?: 'failure' | 'defense' | 'transfer') => void }) {
  const [replay, setReplay] = useState<Replay>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [turn, setTurn] = useState(2);
  const request = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => request.current?.abort(), []);
  const validation = replay?.validation ?? evidence.validation;
  const transcript = evidence.validation.referenceTranscript;
  const maxTurn = (transcript.length - 1) / 2;
  const run = async () => {
    if (busy) return;
    const controller = new AbortController(); request.current = controller;
    const timer = window.setTimeout(() => controller.abort(), 185000);
    setBusy(true); setError(''); setReplay(undefined);
    try {
      const response = await fetch('/api/hub-demo/transfer/replay', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', signal: controller.signal });
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Start the local replay service to run this check again.');
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Replay failed.');
      if (result.runId !== evidence.runId || result.moduleSha256 !== evidence.moduleSha256 || result.modelCalls !== 0 || !result.validation?.passed
        || result.validation.attackCases !== 60 || result.validation.benignTotal !== 40 || result.validation.blocked !== 60 || result.validation.benignPassed !== 40) {
        throw new Error('Replay identity or validation checks failed.');
      }
      setReplay(result);
    } catch (err) { setError(controller.signal.aborted ? 'Replay cancelled or timed out; the saved result remains labeled below.' : (err as Error).message); }
    finally { window.clearTimeout(timer); setBusy(false); }
  };
  return <section className="hub-replay transfer-demo" aria-labelledby="transfer-demo-title">
    <div className="lb-heading"><div><div className="eyebrow">KNOWLEDGE GRAPH / ONE VALIDATED TRANSFER</div><h2 id="transfer-demo-title">Learn it once. Test it elsewhere.</h2><p>A rule learned from a Hub Sudoku grader was retrieved and adapted to a different, multi-turn number game. Here is the measured result.</p></div><span className="lb-snapshot-badge">{replay ? 'Fresh sandbox replay' : 'Saved validated experiment'}<span>1 Haiku adaptation · ${evidence.modelSpendUsd.toFixed(5)}</span></span></div>
    <div className="transfer-flow" aria-label="Knowledge transfer from Mini Sudoku to Number hunt">
      <button className="transfer-node source" onClick={() => onInspect(`inv:${evidence.source.invariant_id}`, 'defense')}><span>01 / LEARNED IN A DIFFERENT ENVIRONMENT</span><strong>Mini Sudoku</strong><small>{evidence.source.env_id}</small><p>Multiple answer blocks let a correct draft hide a wrong final answer.</p><em>Inspect source invariant ↗</em></button>
      <div className="transfer-arrow" aria-hidden="true">→</div>
      <div className="transfer-node rule"><span>02 / RETRIEVED FROM THE GRAPH</span><strong>Reject ambiguous answers</strong><small>Moss + graph · {evidence.retrieval.indexed_documents} Hub records searched</small><p>Use one unambiguous answer. Check the rule’s preconditions before adapting it.</p><em>Returned rank {evidence.retrieval.offered_candidates.indexOf(evidence.source.invariant_id) + 1} · relevance {evidence.source.score.toFixed(3)}</em></div>
      <div className="transfer-arrow" aria-hidden="true">→</div>
      <button className="transfer-node target" onClick={() => onInspect(`env:${evidence.targetId}`)}><span>03 / APPLIED TO AN INDEPENDENT TARGET</span><strong>Number hunt</strong><small>1–40 · higher/lower feedback · up to 7 turns</small><p>Require exactly one tagged integer per reply, across the whole episode.</p><em>Inspect target in graph ↗</em></button>
    </div>
    <div className="transfer-check-heading"><div><h3>Did the rule work on the target?</h3><p>{busy ? 'Replaying the saved adaptation in the OS sandbox…' : replay ? `Rechecked at ${new Date(replay.checkedAt).toLocaleTimeString()}. No model calls made.` : 'Measured in the saved experiment. Replay to recompute the checks locally.'}</p></div><button className="hub-run" disabled={busy} onClick={run}>{busy ? 'Replaying…' : 'Replay validation →'}</button></div>
    {error && <p className="hub-demo-error" role="alert">{error} Start with <code>.venvs/hub/bin/python -m harden.experiments.hub_demo</code>.</p>}
    <div className="transfer-measurements" aria-live="polite"><div><span>Attack reward</span><strong>1.0 <i>→</i> 0.0</strong><small>{validation.blocked}/{validation.attackCases} scripted cases blocked</small></div><div><span>Valid answers preserved</span><strong>{validation.benignPassed}<i> / {validation.benignTotal}</i></strong><small>Reference and harmless-preface variants</small></div><div><span>Real multi-turn play</span><strong>2–6 <i>turns</i></strong><small>Across {validation.seeds} seeded reference episodes</small></div></div>
    <div className="transfer-evidence-grid"><section className="transfer-proof"><span className="eyebrow">ONE SCRIPTED ATTACK VARIANT</span><h3>Listing every guess should not win.</h3><pre>{validation.attackExample.replies[0]}</pre><p>The loose parser credits this response because one candidate matches. The adapted constraint rejects the ambiguous reply. The separate strict target oracle scores it zero.</p><small>Three related attack variants × 20 seeds = 60 replay cases. These are not 60 novel discoveries.</small></section>
      <section className="transfer-proof"><span className="eyebrow">VALID EPISODE / RECORDED SCRIPTED POLICY</span><h3>The game can still be played normally.</h3><div className="transfer-transcript">{transcript.slice(0, 1 + 2 * turn).map(([who, text], index) => <div className={who} key={index}><span>{who === 'agent' ? 'PLAYER' : 'ENVIRONMENT'}</span><p>{text}</p></div>)}</div><div className="transfer-turn-controls"><button disabled={turn <= 0} onClick={() => setTurn(n => n - 1)}>Previous turn</button><span>{turn} / {maxTurn} turns</span><button disabled={turn >= maxTurn} onClick={() => setTurn(n => n + 1)}>Next turn →</button></div></section></div>
    <details className="hub-provenance"><summary>How this was checked</summary><p>Live SpacetimeDB records were queried with Moss. Only Hub findings were eligible: no compiler-game rules, target findings, or previous repairs were offered. We selected a returned rule whose tagged-answer preconditions fit the target. A single Haiku call adapted that rule, without seeing our scripted attack cases. The code was statically checked, then executed in an OS sandbox with no network or API keys.</p><p>Replay validation recomputes the saved code’s 60 attack and 40 benign cases plus the game’s standard gates. It does not call a model or repeat retrieval. The saved retrieval and adaptation are shown above; their original measurement time was {new Date(evidence.checkedAt).toLocaleString()}.</p><p>{evidence.limitations.join(' ')}</p><pre>{evidence.adaptation.code}</pre></details>
    <div className="hub-replay-links"><button onClick={() => onInspect(`inv:${evidence.source.invariant_id}`, 'transfer')}>See the verified transfer edge in the graph →</button></div>
  </section>;
}

import { useEffect, useId, useRef, useState } from 'react';
import { InvariantNetwork } from '../components/InvariantNetwork';
import type { GraphProjection } from '../graph/buildGraph';
import { ReplayStage } from './GameReplay';
import { percent, replayRow, type Demo, type DemoData } from './model';
import { walkthroughExample, type WalkthroughExample } from './walkthrough';
import './walkthrough.css';

export type KnowledgeContext = { graph?: GraphProjection; liveStatus?: string; onInspect?: (id: string) => void };
const steps = ['Initial task', 'RL environment', 'Reward loophole', 'Improved environment', 'Knowledge graph'];
const headings = ['Start with the task.', 'Put the task inside a learning loop.', 'High reward. Wrong behavior.', 'Keep the task. Repair the reward.', 'Turn one failure into reusable knowledge.'];

function RewardLoop({ example, repaired = false }: { example: WalkthroughExample; repaired?: boolean }) {
  return <div className={`reward-loop ${repaired ? 'repaired' : ''}`} role="group" aria-label={repaired ? 'Revised RL environment' : 'Original RL environment'}>
    <div className="loop-topline"><span className="eyebrow">{repaired ? 'ENVIRONMENT V2' : 'ENVIRONMENT V1'}</span><span>RL interaction loop · schematic</span></div>
    <div className="loop-route">
      <div className="loop-node"><span className="loop-symbol">◎</span><strong>Environment</strong><small>{example.observation}</small></div>
      <div className="loop-connector"><span>observation</span><i /><b>→</b></div>
      <div className="loop-node"><span className="loop-symbol">⌘</span><strong>Agent</strong><small>{example.action}</small></div>
      <div className="loop-connector"><span>action</span><i /><b>→</b></div>
      <div className={`loop-node loop-reward ${repaired ? 'fixed' : ''}`}><span className="loop-symbol">{repaired ? '✓' : '↗'}</span><strong>Reward function</strong><small>{repaired ? 'Check the actual task outcome' : 'Score a shortcut for success'}</small></div>
    </div>
    <div className="loop-return"><span>←</span><i /><p>Reward feeds the next policy update</p><i /><span>↵</span></div>
    <div className="loop-rule"><span>{repaired ? 'REVISED REWARD' : 'ORIGINAL REWARD'}</span><p>{repaired ? example.newReward : example.oldReward}</p></div>
  </div>;
}

function Episode({ example, repaired = false }: { example: WalkthroughExample; repaired?: boolean }) {
  const [frame, setFrame] = useState(0), [playing, setPlaying] = useState(false);
  const task = repaired ? example.task : example.exploitTask ?? example.task, call = example.call;
  const policy = repaired ? 'hardened' : 'hacked';
  const row = task ? replayRow(task.rollouts[policy], repaired ? 'strict' : 'loose') : undefined;
  const max = task ? task.info?.prices ? 3 : Math.max(1, (row?.pages?.length ?? 1) - 1) : (call?.transcript.length ?? 1) - 1;
  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => {
      setFrame(value => Math.min(value + 1, max));
      if (frame + 1 >= max) setPlaying(false);
    }, 1100);
    return () => window.clearTimeout(timer);
  }, [playing, frame, max]);
  const turn = call?.transcript[frame];
  return <div className={`story-episode policy-${policy}`}>
    <div className="story-episode-label"><span className="policy-dot" /><strong>{task ? repaired ? example.scripted ? 'Reference solver' : 'Trained on the fixed reward' : 'Reward-hacked policy' : 'Same recorded call'}</strong><span>{task ? example.scripted ? 'Scripted replay' : 'Recorded rollout' : 'Recorded audit'}</span></div>
    <div className="story-stage">{task && row ? <ReplayStage task={task} row={row} frame={frame} name={repaired ? 'Hardened' : 'Reward hacked'} /> : turn && <div className={`story-call-turn ${turn[0].toLowerCase()}`}>
      <span className="speaker-avatar">{turn[0][0]}</span><span className="eyebrow">{turn[0]} · turn {frame + 1}</span><p>{turn[1]}</p>
      {call?.audio?.[frame] && <audio key={`${call.id}-${frame}`} controls preload="none" aria-label={`Listen to ${turn[0]}, turn ${frame + 1}`} src={call.audio[frame]} onPlay={() => setPlaying(false)} />}
    </div>}</div>
    <div className="story-playback"><button onClick={() => { if (frame === max) setFrame(0); setPlaying(value => !value); }}>{playing ? 'Ⅱ Pause' : '▶ Play episode'}</button><button aria-label="Restart episode" onClick={() => { setPlaying(false); setFrame(0); }}>↺</button><input type="range" aria-label="Episode step" min={0} max={max} value={frame} onChange={event => { setPlaying(false); setFrame(Number(event.target.value)); }} /><output aria-label="Episode position">{frame} / {max}</output><button aria-label="Next episode step" disabled={frame === max} onClick={() => { setPlaying(false); setFrame(value => value + 1); }}>Step →</button></div>
  </div>;
}

function Repair({ example, data, demo }: { example: WalkthroughExample; data: DemoData; demo: Demo }) {
  return <>
    <div className="environment-diff">
      <div className="old-environment"><span className="eyebrow">ORIGINAL ENVIRONMENT · V1</span><h4>Reward the appearance of success.</h4><p>{example.oldReward}</p></div>
      <span className="environment-derives" aria-label="Derived from the original environment">→<small>Loophole</small></span>
      <div className="new-environment"><span className="eyebrow">REVISED ENVIRONMENT · V2</span><h4>Reward the required behavior.</h4><p>{example.newReward}</p></div>
    </div>
    <div className="preserved-state"><span>INHERITED FROM V1</span><p>{example.state}</p><span className="preserved-check">✓ Same task</span></div>
    <div className="story-split repair-result"><div>
      <div className="repair-checks">{example.checks.map(check => <span key={check}>✓ {check}</span>)}</div>
      <div className="same-exploit"><span className="eyebrow">{example.call ? 'SAME CALL / TWO JUDGES' : example.sameActions ? 'SAME EXPLOIT / TWO REWARDS' : 'SAME HACKED POLICY / TWO ENVIRONMENTS'}</span><div><p><small>Original</small><strong>{example.before}</strong></p><span>→</span><p><small>Revised</small><strong>{example.after}</strong></p></div><p>{example.result}</p></div>
      {data.kind === 'voice' ? <div className="positive-check"><strong>{percent(data.summary.asr_before)} → {percent(data.summary.asr_after)}</strong><p>Wrong calls passed · full recorded audit</p><span>Honest calls passed: {percent(data.summary.benign_before)} → {percent(data.summary.benign_after)}</span></div> : <div className="positive-check"><strong>{percent(demo.scores.base?.strict ?? 0)} → {percent(demo.scores.hardened?.strict ?? 0)}</strong><p>Mean true score · base → hardened · all {demo.samples} held-out tasks</p><span>Hardened score on the featured task: {example.correct}</span></div>}
    </div><div>{example.call ? <div className="policy-decision"><span className="eyebrow">POLICY-CORRECT OUTCOME</span><strong>{example.correct}</strong><p>The recorded agent chose {example.call.decision.toUpperCase()}. The hardened judge now rejects that decision.</p><details><summary>Inspect the revised judge prompt</summary><pre>{data.kind === 'voice' ? data.judges.hardened : ''}</pre></details></div> : <Episode example={example} repaired />}</div></div>
    <p className="story-evidence-note">{data.kind === 'voice' ? 'This demonstrates a better reward judge on recorded calls. It does not show a retrained voice agent.' : demo.placeholder ? 'V1 and V2 illustrate the recorded loose and strict graders. The reference solver is scripted; this comparison is not a new training run.' : `V1 and V2 illustrate the loose and strict environments used in the recorded GPU runs. This featured example is ${example.taskIndex! + 1} of ${demo.samples}; aggregate scores include every held-out task.`}</p>
  </>;
}

function KnowledgeGraph({ example, demo, graph, liveStatus, onInspect }: { example: WalkthroughExample; demo: Demo } & KnowledgeContext) {
  const [selected, setSelected] = useState('constraint'), [showLive, setShowLive] = useState(false);
  const arrow = useId();
  const nodes = [
    { id: 'task', x: 145, y: 75, label: 'Initial task', sub: demo.title, description: example.prompt, kind: 'task' },
    { id: 'original', x: 445, y: 75, label: 'Environment v1', sub: 'Original reward', description: example.oldReward, kind: 'environment' },
    { id: 'failure', x: 745, y: 75, label: 'Reward loophole', sub: example.shortFailure, description: example.failure, kind: 'failure' },
    { id: 'result', x: 145, y: 260, label: 'Validation evidence', sub: `${example.before} → ${example.after}`, description: example.result, kind: 'result' },
    { id: 'revised', x: 445, y: 260, label: 'Environment v2', sub: 'Derived from v1', description: `${example.state}. ${example.newReward}`, kind: 'environment' },
    { id: 'constraint', x: 745, y: 260, label: 'Reusable constraint', sub: 'Extracted from the failure', description: example.invariant, kind: 'constraint' },
  ];
  const edges = [
    { path: 'M250 75H335', x: 294, y: 60, label: 'defines' },
    { path: 'M550 75H635', x: 594, y: 60, label: 'reveals' },
    { path: 'M745 117V215', x: 787, y: 170, label: 'yields' },
    { path: 'M640 260H555', x: 594, y: 245, label: 'enforced in' },
    { path: 'M340 260H255', x: 294, y: 245, label: 'validated by' },
  ];
  const current = nodes.find(node => node.id === selected)!;
  return <>
    <div className="lineage-heading"><span className="eyebrow">EVIDENCE MAP / THIS EXAMPLE</span><span>Select a node to inspect its meaning</span></div>
    <div className="lineage-canvas"><svg viewBox="0 0 890 330" role="group" aria-label="Example knowledge graph: task, original environment, reward loophole, reusable constraint, revised environment and validation">
      <defs><marker id={arrow} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7" fill="#647c8a" /></marker></defs>
      {edges.map(edge => <g key={edge.label}><path d={edge.path} className="lineage-edge" markerEnd={`url(#${arrow})`} /><text x={edge.x} y={edge.y} className="lineage-edge-label" textAnchor="middle">{edge.label}</text></g>)}
      {nodes.map(node => <g key={node.id} role="button" tabIndex={0} aria-label={`Inspect ${node.label}`} aria-pressed={selected === node.id} onClick={() => setSelected(node.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(node.id); } }} className={`lineage-node ${node.kind} ${selected === node.id ? 'selected' : ''}`}>
        <rect x={node.x - 105} y={node.y - 39} width="210" height="78" rx="12" /><circle cx={node.x - 84} cy={node.y - 13} r="3" /><text x={node.x - 72} y={node.y - 9} className="lineage-node-label">{node.label}</text><text x={node.x - 84} y={node.y + 15} className="lineage-node-sub">{node.sub}</text>
      </g>)}
    </svg></div>
    <div className="lineage-inspector" aria-live="polite"><span className="eyebrow">{current.label}</span><p>{current.description}</p></div>
    <p className="story-evidence-note">This map explains the recorded example. It does not publish new records or establish transfer to other tasks.</p>
    <div className="knowledge-store-link"><div><span className="eyebrow">THE SHARED KNOWLEDGE STORE</span><h4>Connect failures, defenses and transfer tests.</h4><p>{graph?.nodes.length ? `${graph.nodes.filter(node => node.kind === 'environment').length} environments · ${graph.nodes.filter(node => node.kind === 'invariant').length} invariants · ${graph.edges.filter(edge => edge.kind === 'applied_to').length} recorded transfer outcomes` : 'Open Live audits to inspect the recorded knowledge store.'}</p></div><button onClick={() => setShowLive(value => !value)} aria-expanded={showLive}>{showLive ? 'Hide recorded graph ↑' : 'Show recorded graph ↓'}</button><a href="#live">Open Live audits ↗</a></div>
    {showLive && <section className="story-live-graph" aria-label="Recorded knowledge store"><div className="story-live-heading"><span>{liveStatus === 'live' ? 'Live subscription' : 'Connection: ' + (liveStatus ?? 'not available')}</span><p>Existing audit records. Select a node to open its evidence in Live audits.</p></div>{graph?.nodes.length ? <InvariantNetwork graph={graph} containerId="showcase-network" onSelect={id => onInspect?.(id)} /> : <p className="story-graph-empty">No knowledge records are available yet. The example map above uses the bundled demo evidence.</p>}</section>}
  </>;
}

export function DemoWalkthrough({ demo, data, ...knowledge }: { demo: Demo; data: DemoData } & KnowledgeContext) {
  const [step, setStep] = useState(0);
  const section = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);
  useEffect(() => { if (firstRender.current) firstRender.current = false; else heading.current?.focus({ preventScroll: true }); }, [step]);
  if ((data.kind === 'voice' ? data.calls : data.tasks).length === 0) return <p className="showcase-empty">No recorded examples are available for this walkthrough.</p>;
  const example = walkthroughExample(demo, data);
  function navigate(next: number) { setStep(next); section.current?.scrollIntoView?.({ block: 'start' }); }
  return <section ref={section} className="demo-walkthrough" aria-label="Guided demo">
    <nav className="story-steps" aria-label="Demo steps">{steps.map((label, index) => <button key={label} aria-current={step === index ? 'step' : undefined} className={index < step ? 'visited' : ''} onClick={() => navigate(index)}><span>{index < step ? '✓' : String(index + 1).padStart(2, '0')}</span><strong>{label}</strong></button>)}</nav>
    <div className={`story-panel story-step-${step}`}>
      <div className="story-heading"><span className="eyebrow">{String(step + 1).padStart(2, '0')} / {steps[step].toUpperCase()}</span><h3 ref={heading} tabIndex={-1}>{headings[step]}</h3></div>
      {step === 0 && <div className="story-split initial-task"><div className="task-brief"><span className="eyebrow">THE USER’S REQUEST</span><h4>{example.taskTitle}</h4><blockquote>{example.prompt}</blockquote><div className="task-success"><span>SUCCESS MEANS</span><p>{example.success}</p></div></div><div className="initial-environment"><div className="initial-environment-label"><span className="status-light" />Initial environment state</div>{example.task ? <div className="story-stage policy-hardened"><ReplayStage task={example.task} row={example.task.rollouts.hardened} frame={0} name="Initial environment" /></div> : <div className="voice-task"><div className="call-wave" aria-hidden="true">{[14, 24, 40, 28, 55, 36, 70, 48, 29, 58, 38, 20, 32, 15].map((height, index) => <i key={index} style={{ height }} />)}</div><h4>Electronics refund desk</h4><p>A customer wants to return an opened, working item bought about three months ago.</p><div><span>Observe</span>Request + order facts</div><div><span>Decide</span>Refund / escalate / deny</div><div><span>Evaluate</span>Follow the refund policy</div></div>}</div></div>}
      {step === 1 && <><p className="story-intro">The environment exposes observations and actions. Its reward tells the agent which behavior to repeat.</p><RewardLoop example={example} /><div className="loop-question"><span>THE ASSUMPTION</span><p>Does a high reward actually mean the task was done correctly?</p></div></>}
      {step === 2 && <div className="story-split loophole-reveal"><Episode example={example} /><div className="loophole-explanation"><span className="loophole-tag">LOOPHOLE FOUND</span><h4>{example.shortFailure}.</h4><p>{example.failure}</p><div className="loophole-metrics"><div><span>Original {example.call ? 'judge' : 'reward'}</span><strong>{example.before}</strong></div><div><span>{example.call ? 'Policy requires' : 'True task score'}</span><strong>{example.call ? example.correct : percent(example.task!.rollouts.hacked.strict)}</strong></div></div><p className="story-metric-caption">Final recorded outcome for this example</p><div className="failure-cause"><span>WHY IT WORKS</span><p>{example.oldReward}</p></div></div></div>}
      {step === 3 && <Repair example={example} data={data} demo={demo} />}
      {step === 4 && <KnowledgeGraph example={example} demo={demo} {...knowledge} />}
    </div>
    <div className="story-navigation"><button disabled={step === 0} onClick={() => navigate(step - 1)}>← Back</button><span>{step + 1} of {steps.length}<small>{demo.placeholder ? 'Scripted example · recorded scores' : demo.kind === 'voice' ? 'Recorded judge audit' : `Recorded GPU run · example ${example.taskIndex! + 1} of ${demo.samples}`}</small></span>{step < steps.length - 1 ? <button className="showcase-primary" onClick={() => navigate(step + 1)}>Next: {steps[step + 1]} →</button> : <button onClick={() => navigate(0)}>↺ Restart demo</button>}</div>
  </section>;
}

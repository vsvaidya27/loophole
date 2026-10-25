import { useEffect, useState } from 'react';
import { featuredTask, percent, policies, policyCaption, policyNames, replayLength, replayRow, type Demo, type GameData, type RewardMode, type Rollout, type Task } from './model';
import { presentShopPage, shopStyles } from './shopReplay';
import { presentSnakePage, snakeStyles } from './snakeReplay';

function PriceChart({ task, frame }: { task: Task; frame: number }) {
  const prices = task.info?.prices ?? [];
  const future = task.info?.future;
  if (!prices.length || future === undefined) return null;
  const all = [...prices, future], low = Math.min(...all) - 2, high = Math.max(...all) + 2;
  const x = (i: number) => 24 + i * 25, y = (p: number) => 130 - (p - low) / (high - low) * 100;
  return <svg className="price-chart" viewBox="0 0 310 165" role="img" aria-label={`Simulated prices: ${prices.join(', ')}. Future price: ${future}`}>
    {[30, 65, 100, 130].map(n => <line key={n} x1="20" x2="290" y1={n} y2={n} className="chart-gridline" />)}
    <path d={prices.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p)}`).join(' ')} fill="none" stroke="var(--mint)" strokeWidth="2" />
    {prices.map((p, i) => <circle key={i} cx={x(i)} cy={y(p)} r="2.5" fill="var(--mint)" />)}
    {frame >= 2 && <><path d={`M${x(7)},${y(prices[7])}L${x(10)},${y(future)}`} stroke="var(--amber)" strokeWidth="2" strokeDasharray="4 5" /><circle cx={x(10)} cy={y(future)} r="4" fill="var(--amber)" /><text x={x(10)} y={y(future) - 12}>{future}</text></>}
    <text x={x(0)} y="155">History</text><text x={x(7)} y="155" textAnchor="middle">Now · {prices[7]}</text><text x={x(10)} y="155" textAnchor="middle">+3 ticks</text>
  </svg>;
}

// Stored web pages are visual evidence. The sandbox and CSP disable scripts, requests, and forms.
const pageStyles = `*{box-sizing:border-box}body{margin:0;background:#f0ece6;color:#3d3832;font:11px/1.5 system-ui,sans-serif}.wf{padding:12px}.wf-bar{display:flex;align-items:center;gap:4px;padding-bottom:9px;border-bottom:1px solid #ddd8d3}.wf-bar span{width:5px;height:5px;background:#948e88;border-radius:50%}.wf-bar em{font:10px system-ui;margin-left:7px}.wf-goal{font-size:10px;color:#69645e;margin:12px 0}.wf-row{padding:7px;display:flex;gap:8px;align-items:center;border:1px solid transparent;border-radius:5px;margin:4px 0;flex-wrap:wrap}.wf-row>b{font:9px monospace;color:#807b74}.wf-row.hot{border-color:#2c5d8966;background:#d9e2eb}.wf-row label{font-size:10px;min-width:55px}.wf-input{background:#e9e4df;border:1px solid #dad5d0;padding:5px 8px;flex:1;min-width:80px}.wf-check{display:flex;align-items:center;gap:7px;font-size:10px}.wf-check i{height:10px;width:10px;border:1px solid #87817a;display:inline-block}.wf-check i.on{background:#2c5d89;border-color:#2c5d89}.wf-btn{background:#ced7e0;color:#245681;border:1px solid #88a1b9;border-radius:4px;padding:5px 12px}.wf-ad{font-size:9px;color:#a67ba2}.wf-end{padding:9px;background:#d6dfe8;color:#295b87;margin-top:9px;font-size:10px}.wf-end.shallow{background:#e9dbd8;color:#9a3b2e}.wf-product{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.wf-price{color:#2c5d89}.wf-banner{padding:10px;background:#e6e1db;border-radius:5px}.sn{padding:12px;height:100%;display:flex;flex-direction:column;gap:10px}.sn-bar{display:flex;justify-content:space-between;gap:6px;font:10px 'Fragment Mono',ui-monospace,monospace;color:#69645e}.sn-grid{display:grid;grid-template-columns:repeat(var(--n),1fr);gap:4px;width:min(100%,260px);margin:0 auto;aspect-ratio:1}.sn-grid i{border-radius:5px;background:#e9e4df;border:1px solid #dad5d0}.sn-grid i.b{background:#88a1b9;border-color:#7690a9}.sn-grid i.h{background:#2c5d89;border-color:#245681;box-shadow:0 0 0 2px #2c5d8933}.sn-grid i.f{background:#b98236;border-color:#9c6b27;border-radius:50%;transform:scale(.72)}.sn-end{padding:9px;background:#d6dfe8;color:#295b87;font-size:10px;text-align:center;border-radius:4px}.sn-end.bad{background:#e9dbd8;color:#9a3b2e}.sn-end.shallow{background:#e6e1db;color:#5b5650}`;

function WebPage({ html, name }: { html: string; name: string }) {
  const shop = presentShopPage(html), snake = shop ? null : presentSnakePage(html);
  return <iframe className={`captured-page${shop ? ' captured-shop' : ''}${snake ? ' captured-snake' : ''}`} title={`${name} ${snake ? 'game' : 'browser'} replay`} sandbox="" srcDoc={`<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'"><style>${pageStyles}${shop || snake ? shopStyles : ''}${snake ? snakeStyles : ''}</style></head><body>${shop ?? snake ?? html}</body></html>`} />;
}

export function ReplayStage({ task, row, frame, name }: { task: Task; row: Rollout; frame: number; name: string }) {
  if (row.pages?.length) {
    const index = Math.min(frame, row.pages.length - 1);
    const action = row.transcript?.filter(([speaker]) => speaker === 'agent')[index - 1]?.[1];
    return <><WebPage html={row.pages[index]} name={name} /><div className="frame-caption">{action ? action.replace(/<\/?answer>/g, '') : 'Waiting for the first action'}</div></>;
  }
  if (task.info?.prices) return <><PriceChart task={task} frame={frame} /><div className="order-label">{frame ? row.answer || row.completion : 'Waiting for order'}</div><div className="frame-caption">{frame >= 2 ? 'Future price revealed' : 'Simulated market · no real money'}</div></>;
  return <pre>{row.answer ?? row.completion ?? 'No recorded frames'}</pre>;
}

function ScoreBar({ label, value, paid = false }: { label: string; value: number; paid?: boolean }) {
  return <div className={`replay-score ${paid ? 'paid' : ''}`}><span>{label}</span><div><i style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} /></div><strong>{percent(value)}</strong></div>;
}

function ReplayTask({ demo, task, mode }: { demo: Demo; task: Task; mode: RewardMode }) {
  const [frame, setFrame] = useState(0), [playing, setPlaying] = useState(false), [speed, setSpeed] = useState(1);
  const maxFrame = replayLength(task, mode);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => {
      setFrame(Math.min(frame + 1, maxFrame));
      if (frame + 1 >= maxFrame) setPlaying(false);
    }, 700 / speed);
    return () => window.clearTimeout(timer);
  }, [playing, frame, maxFrame, speed]);
  function play() { if (frame === maxFrame) setFrame(0); setPlaying(!playing); }
  return <>
    <div className="replay-controls">
      <button className="showcase-primary" onClick={play}>{playing ? 'Ⅱ Pause replay' : '▶ Play replay'}</button>
      <button aria-label="Restart replay" onClick={() => { setPlaying(false); setFrame(0); }}>↺</button>
      <button aria-label="Next replay step" disabled={frame === maxFrame} onClick={() => { setPlaying(false); setFrame(Math.min(frame + 1, maxFrame)); }}>Step →</button>
      <label className="replay-scrubber"><span>Replay step</span><input aria-label="Replay step" type="range" min="0" max={maxFrame} value={frame} onChange={event => { setPlaying(false); setFrame(Number(event.target.value)); }} /></label>
      <output aria-label="Current replay step">{frame} / {maxFrame}</output>
      <select aria-label="Playback speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={0.5}>0.5×</option><option value={1}>1× speed</option><option value={2}>2× speed</option></select>
    </div>
    <div className="policy-replays">{policies.map(policy => {
      const row = replayRow(task.rollouts[policy], mode);
      const gap = row.loose > row.strict + 0.01;
      return <article className={`policy-replay policy-${policy}`} key={policy} aria-label={`${policyNames[policy]} replay`}>
        <div className="policy-heading"><span className="policy-dot" /><div><h4>{policyNames[policy]}</h4><p>{policyCaption(demo.placeholder, policy)}</p></div><span className="policy-number">0{policies.indexOf(policy) + 1}</span></div>
        <div className="policy-stage"><ReplayStage task={task} row={row} frame={frame} name={policyNames[policy]} /></div>
        <div className="replay-scores"><ScoreBar label="True score" value={row.strict} /><ScoreBar label="Loose reward" value={row.loose} paid /></div>
        <div className={`reward-gap ${gap ? 'has-gap' : ''}`}>{gap ? '↗ Reward exceeds the true score' : 'Reward matches the true score'}</div>
        <details className="replay-output"><summary>{row.transcript ? 'Inspect recorded actions' : 'Inspect submitted answer'}</summary><pre>{row.transcript ? row.transcript.map(([who, text]) => `${who.toUpperCase()}\n${text}`).join('\n\n') : row.completion}</pre>{row.best_loose && gap && <p>The loose parser rewarded: <code>{row.best_loose}</code></p>}</details>
      </article>;
    })}</div>
  </>;
}

export function GameReplay({ demo, data }: { demo: Demo; data: GameData }) {
  const [taskIndex, setTaskIndex] = useState(() => featuredTask(data.tasks));
  const [mode, setMode] = useState<RewardMode>('strict');
  const task = data.tasks[taskIndex];
  if (!task) return <p className="showcase-empty">No recorded tasks are available for this demo.</p>;
  return <section className="showcase-panel replay-section" aria-label="Interactive policy replay">
    <div className="showcase-section-heading"><div><span className="eyebrow">SAME TASK / THREE POLICIES</span><h3>Inspect the behavior</h3><p>Step through the recorded actions. Scores below are the final outcome for this example.</p>{demo.shown && <p className="replay-selection-note">{demo.shown}</p>}</div><label className="example-picker">Example<select aria-label="Replay example" value={taskIndex} onChange={event => setTaskIndex(Number(event.target.value))}>{data.tasks.map((item, index) => <option key={index} value={index}>{item.board ? `Board ${item.board} of ${demo.samples}` : `${String(index + 1).padStart(2, '0')} of ${data.tasks.length}`}</option>)}</select></label></div>
    <details className="task-instructions"><summary>{task.question.split('\n')[0]}</summary><pre>{task.question}</pre></details>
    {data.kind === 'multi' && <label className="replay-environment-picker">Replay environment<select aria-label="Replay environment" value={mode} onChange={event => setMode(event.target.value as RewardMode)}><option value="strict">Strict reward</option><option value="loose">Loose reward</option></select><span>Separate recorded episodes; actions can differ between environments.</span></label>}
    <ReplayTask key={`${taskIndex}-${mode}`} demo={demo} task={task} mode={mode} />
    <p className="replay-footnote">True score uses the strict reward. Loose reward is what the hackable grader pays for the same policy.{data.kind === 'multi' ? ' The two scores come from separate recorded episodes on the same task.' : ' Both scores evaluate the same submitted completion.'}{demo.placeholder && ' These policies are scripted; no training performance is implied.'}</p>
  </section>;
}

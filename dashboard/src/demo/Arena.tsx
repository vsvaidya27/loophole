import { useEffect, useRef, useState } from 'react';
import { playEpisode, seeded, trainStep, untrained, type Episode, type Policy } from './agent';
import { HIGH, LOW, MAX_TURNS, type Mode } from './higherLower';
import type { DemoData } from './data';

export const STEPS = 60;
const STEP_MS = 260;
interface Point { step: number; paid: number; real: number; loss: number; numbers: number }
interface Lane { mode: Mode; policy: Policy; random: () => number; points: Point[]; sample: Episode }

/** Over 100 games: how often the grader pays, how often the same replies really win under the
 *  exact rules, how often a loss is paid, and how many numbers the agent writes per reply. */
function measure(policy: Policy, mode: Mode, seed: number, step: number): Point {
  const random = seeded(seed);
  let paid = 0, real = 0, loss = 0, numbers = 0, replies = 0;
  for (let i = 0; i < 100; i++) {
    const episode = playEpisode(policy, mode, random);
    paid += episode.reward;
    if (episode.realWin) real += 1;
    else loss += episode.reward;
    for (const turn of episode.turns) { numbers += (turn.reply.match(/\d+/g) ?? []).length; replies += 1; }
  }
  return { step, paid: paid / 100, real: real / 100, loss: loss / 100, numbers: numbers / Math.max(1, replies) };
}

function startLane(mode: Mode, seed: number): Lane {
  const policy = untrained();
  return { mode, policy, random: seeded(seed), points: [measure(policy, mode, seed * 31, 0)], sample: playEpisode(policy, mode, seeded(seed + 5)) };
}

function advance(lane: Lane): Lane {
  const { policy, stats } = trainStep(lane.policy, lane.mode, lane.random);
  const step = lane.points.length;
  return { ...lane, policy, sample: stats.sample, points: [...lane.points, measure(policy, lane.mode, lane.points.length * 977 + (lane.mode === 'shipped' ? 1 : 2), step)] };
}

const percent = (x: number) => `${Math.round(x * 100)}%`;

function shortReply(reply: string) {
  const count = (reply.match(/\d+/g) ?? []).length;
  return reply.length > 44 ? `${reply.slice(0, 42)}… (${count} numbers)` : reply;
}

function Transcript({ episode }: { episode: Episode }) {
  return <ol className="transcript" aria-label="The agent's latest game">
    <li className="from-game">I'm thinking of a number from {LOW} to {HIGH}. You have {MAX_TURNS} guesses.</li>
    {episode.turns.flatMap((turn, i) => [
      <li key={`a${i}`} className="from-agent"><code>{shortReply(turn.reply)}</code></li>,
      <li key={`g${i}`} className={`from-game${turn.message.startsWith('Correct') ? ' correct' : ''}`}>{turn.message.replace(/ Out of guesses.*/, ' Out of guesses.')}</li>,
    ])}
    {episode.reward > 0 && !episode.realWin && <li className="note">Paid in full, but a loss under the real rules.</li>}
  </ol>;
}

function Chart({ points }: { points: Point[] }) {
  const w = 520, h = 190, pad = 44;
  const x = (step: number) => pad + (step / STEPS) * (w - pad - 12), y = (v: number) => 12 + (1 - v) * (h - 36);
  const at = (step: number, v: number) => `${x(step).toFixed(1)},${y(v).toFixed(1)}`;
  const line = (key: 'paid' | 'real') => points.map(p => at(p.step, p[key])).join(' ');
  const band = [...points.map(p => at(p.step, p.paid)), ...[...points].reverse().map(p => at(p.step, p.paid - p.loss))].join(' ');
  const last = points[points.length - 1];
  return <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img"
    aria-label={`After ${last.step} steps the grader pays ${percent(last.paid)} of games, the agent really wins ${percent(last.real)}, and ${percent(last.loss)} are paid for a loss.`}>
    {[0, 0.5, 1].map(v => <g key={v}><line x1={pad} x2={w - 12} y1={y(v)} y2={y(v)} className="grid" /><text x={pad - 8} y={y(v) + 4} textAnchor="end" className="axis">{percent(v)}</text></g>)}
    <text x={w - 12} y={h - 4} textAnchor="end" className="axis">training step {last.step} of {STEPS}</text>
    <polygon points={band} className="band" />
    <polyline points={line('paid')} className="series paid" />
    <polyline points={line('real')} className="series real" />
    <circle cx={x(last.step)} cy={y(last.paid)} r={4.5} className="head paid" />
    <circle cx={x(last.step)} cy={y(last.real)} r={4.5} className="head real" />
  </svg>;
}

function LaneView({ lane, title, note }: { lane: Lane; title: string; note: string }) {
  const last = lane.points[lane.points.length - 1];
  return <section className={`lane lane-${lane.mode}`}>
    <header><h3>{title}</h3><p>{note}</p></header>
    <div className="figures">
      <div className="figure paid"><strong>{percent(last.paid)}</strong><span>games the grader pays for</span></div>
      <div className="figure real"><strong>{percent(last.real)}</strong><span>games really won</span></div>
      <div className={`figure loss${Math.round(last.loss * 100) > 0 ? ' some' : ''}`}><strong>{percent(last.loss)}</strong><span>paid for a loss</span></div>
      <div className="figure"><strong>{last.numbers.toFixed(1)}</strong><span>numbers per reply</span></div>
    </div>
    <div className="lane-body">
      <div className="chart-wrap">
        <div className="legend" aria-hidden="true"><span className="paid"><i />grader pays</span><span><i />really won</span><span className="loss"><i />paid for a loss</span></div>
        <Chart points={lane.points} />
      </div>
      <Transcript episode={lane.sample} />
    </div>
  </section>;
}

export function Arena({ data, running, finished, speed, onDone }: { data: DemoData; running: boolean; finished: boolean; speed: number; onDone: () => void }) {
  const [lanes, setLanes] = useState(() => [startLane('shipped', 101), startLane('hardened', 202)]);
  const done = useRef(false);
  const steps = lanes[0].points.length - 1;

  useEffect(() => {
    if (!running || steps >= STEPS) return;
    const timer = window.setTimeout(() => setLanes(current => current.map(advance)), STEP_MS / speed);
    return () => window.clearTimeout(timer);
  }, [running, steps, speed]);

  useEffect(() => {
    if (steps >= STEPS && !done.current) { done.current = true; onDone(); }
  }, [steps, onDone]);

  const [shipped, hardened] = lanes.map(lane => lane.points[lane.points.length - 1]);
  return <div className="arena">
    <div className="lanes">
      <LaneView lane={lanes[0]} title="Paid by the shipped reward" note="Separate earlier higher/lower game, ported to this browser." />
      <LaneView lane={lanes[1]} title="Paid by the hardened reward" note="That earlier game's patch, not the Number hunt transfer module." />
    </div>
    {finished && <p className="result">
      Same agent, same {STEPS} steps. Paid by the shipped reward it learned to list numbers: the grader paid for {percent(shipped.paid)} of its games, but it really won {percent(shipped.real)}.
      Paid by the hardened reward it learned to search, and really won {percent(hardened.real)}.
    </p>}
    <p className="fine evidence">On a GPU, a language model ({data.gpu_evidence.model}) shows the same split on {data.gpu_evidence.game}: hardened, {data.gpu_evidence.hardened}; hackable, {data.gpu_evidence.hackable}.</p>
  </div>;
}

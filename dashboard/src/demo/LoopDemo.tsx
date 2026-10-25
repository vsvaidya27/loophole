import { useMemo } from 'react';
import { Arena } from './Arena';
import { Constellation, type GraphPhase } from './Constellation';
import type { DemoData } from './data';
import { Recall } from './panels';
import { TransferGame, TransferAttack, TransferPatch, TransferResult } from './TransferPanels';
import { transferGraph, report } from './transfer';
import { ACTS, buildBeats, progressIn, usePlayback, type ActId } from './script';

const COPY: Record<ActId, { title: string; lede: string }> = {
  1: { title: 'A different game. The same loophole.', lede: 'Before training, check whether an independent multi-turn number game rewards answers that break its rules.' },
  2: { title: 'Where the graph learned it', lede: 'These five candidates came from earlier Hub environment audits. One Mini Sudoku rule was selected and transferred to Number hunt.' },
  3: { title: 'Check the reward gap', lede: 'A scripted reply earns full reward from the loose grader and zero from the strict oracle. This is recorded experiment evidence.' },
  4: { title: 'Adapt a proven idea', lede: 'One Haiku call turns the selected source rule into a constraint for this target. Test attacks and valid play in a sandbox.' },
  5: { title: 'Verify the transfer', lede: 'The saved validation blocks ambiguous replies while preserving normal multi-turn play. The graph records the tested application.' },
  6: { title: 'Why hardening matters for learning', lede: 'A separate browser illustration trains a small agent on the earlier higher/lower game. This is not an LLM training run from the transfer experiment.' },
};

export function LoopDemo({ data, autoplay = false, embedded = false }: { data: DemoData; autoplay?: boolean; embedded?: boolean }) {
  const graphData = useMemo(() => transferGraph(data), [data]);
  const beats = useMemo(() => buildBeats(), []);
  const play = usePlayback(beats, autoplay);
  const { beat, index, playing, speed } = play;
  const act = beat.act;
  const step = (a: ActId) => progressIn(beats, index, a);
  const hardened = act >= 5;
  const phase: GraphPhase = act === 1 ? 'game'
    : act === 2 ? (['graph', 'query', 'handoff'][step(2)] as GraphPhase)
    : hardened ? 'learned' : 'loop';

  const panel = (() => {
    switch (act) {
      case 1: return <TransferGame flaw={step(1) >= 1} />;
      case 2: return <Recall data={graphData} step={step(2)} />;
      case 3: return <TransferAttack summary={step(3) >= 1} />;
      case 4: return <TransferPatch checked={step(4) >= 1} />;
      case 5: return <TransferResult details={step(5) >= 1} />;
      default: return null;
    }
  })();

  return <div className={`loop-demo act-${act}${embedded ? ' embedded' : ''}`}>
    <header className="demo-bar">
      <a className="mark" href="/" aria-label="Back to the live dashboard"><span aria-hidden="true">∞</span> loophole</a>
      <nav className="acts" aria-label="Acts">
        {ACTS.map(a => <button key={a.id} className={a.id === act ? 'current' : a.id < act ? 'past' : undefined}
          aria-current={a.id === act ? 'step' : undefined} onClick={() => play.jump(a.id)}>
          <span className="n">{a.id}</span>{a.name}
        </button>)}
      </nav>
      <div className="transport">
        <button onClick={play.back} aria-label="Previous step" disabled={index === 0}>◀</button>
        <button className="play" onClick={() => play.setPlaying(!playing)} aria-label={playing ? 'Pause' : 'Play'}>{playing ? 'Pause' : 'Play'}</button>
        <button onClick={play.next} aria-label="Next step" disabled={index === beats.length - 1}>▶</button>
        <button onClick={() => play.setSpeed(speed === 1 ? 2 : 1)} aria-label="Playback speed">{speed}×</button>
        <button onClick={play.restart}>Restart</button>
      </div>
      <div className="beat-progress" aria-hidden="true">
        <i key={`${index}-${playing}-${speed}`} className={playing && beat.ms ? 'running' : undefined} style={{ animationDuration: `${beat.ms / speed}ms` }} />
      </div>
    </header>

    <main className={act === 6 ? 'stage-wide' : 'stage-split'}>
      {act === 6
        ? <>
          <div className="act-head"><h1>{COPY[6].title}</h1><p>{COPY[6].lede}</p></div>
          <Arena data={data} running={beat.key === 'train' && playing} finished={beat.key === 'result'} speed={speed} onDone={play.next} />
          {beat.key === 'train' && !playing && <button className="start-training" onClick={() => play.setPlaying(true)}>Start training</button>}
        </>
        : <>
          <section className="stage" aria-label="Knowledge graph">
            <Constellation data={graphData} phase={phase} hardened={hardened} flaw={act === 1 && step(1) >= 1} />
          </section>
          <section className="narrative" aria-live="polite">
            <div className="act-head" key={act}><h1>{COPY[act].title}</h1><p>{COPY[act].lede}</p></div>
            {panel}
          </section>
        </>}
    </main>

    <footer className="demo-foot">
      <p className="source">{act === 6 ? 'Browser learning illustration on the earlier higher/lower game; separate from the transfer measurements.' : `Saved experiment ${report.runId} · ${new Date(report.checkedAt).toLocaleDateString()} · playback makes no model calls or graph writes.`}</p>
      <p className="keys">Space plays or pauses. Arrow keys step. 1 to 6 jump to an act. S changes speed.</p>
    </footer>
  </div>;
}

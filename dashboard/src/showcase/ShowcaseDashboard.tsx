import { useEffect, useState } from 'react';
import { GameReplay } from './GameReplay';
import { VoiceReplay } from './VoiceReplay';
import { DemoWalkthrough, type KnowledgeContext } from './DemoWalkthrough';
import { demos, evidenceLabel, percent, policies, policyCaption, policyNames, sourceRevision, type Demo, type DemoData } from './model';
import './showcase.css';

export function DemoIcon({ id }: { id: string }) {
  return <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {id === 'trading' && <><path d="M4 5v22h24M7 21l6-7 5 3 10-12M22 5h6v6" /></>}
    {id === 'webagent' && <><rect x="3" y="5" width="26" height="22" rx="3" /><path d="M3 11h26M7 8h1m3 0h1M9 16h14M9 21h8" /><path d="m22 20 4 8 2-4 4-2z" fill="currentColor" stroke="none" /></>}
    {id === 'snake' && <><rect x="3" y="3" width="26" height="26" rx="3" /><path d="M8 22h6v-8h8V9" strokeWidth="3" /><circle cx="22" cy="9" r="1.2" fill="currentColor" stroke="none" /><circle cx="22" cy="23" r="2.2" fill="currentColor" stroke="none" /></>}
    {id === 'voice' && <><rect x="12" y="3" width="8" height="16" rx="4" /><path d="M7 13v2a9 9 0 0 0 18 0v-2M16 24v5M12 29h8" /></>}
  </svg>;
}

function selectedFromHash() { return demos.find(demo => window.location.hash === `#showcase/${demo.id}`)?.id ?? demos[0].id; }

function DemoStats({ demo }: { demo: Demo }) {
  if (demo.summary) return <div className="showcase-stats voice-stats">
    <article className="showcase-stat policy-hacked"><span className="eyebrow">WRONG CALLS PASSED</span><div className="stat-transition"><strong>{percent(demo.summary.asr_before)}</strong><span>→</span><strong>{percent(demo.summary.asr_after)}</strong></div><p>Baseline judge → hardened judge</p></article>
    <article className="showcase-stat policy-hardened"><span className="eyebrow">HONEST CALLS PASSED</span><div className="stat-transition"><strong>{percent(demo.summary.benign_before)}</strong><span>→</span><strong>{percent(demo.summary.benign_after)}</strong></div><p>Baseline judge → hardened judge</p></article>
    <article className="showcase-stat"><span className="eyebrow">EVIDENCE TO EXPLORE</span><strong className="stat-value">{demo.samples}<small>selected calls</small></strong><p>Two judge verdicts for each call</p></article>
  </div>;
  return <div className="showcase-stats">{policies.map(policy => {
    const score = demo.scores[policy];
    return <article className={`showcase-stat policy-${policy}`} key={policy}><div className="stat-heading"><span className="policy-dot" /><h3>{policyNames[policy]}</h3><span>{policyCaption(demo.placeholder, policy)}</span></div><div className="stat-values"><div><strong>{score ? percent(score.strict) : '—'}</strong><span>True score</span></div><div><strong>{score ? percent(score.loose) : '—'}</strong><span>Loose reward</span></div></div><p>Mean across {demo.samples} identical tasks</p></article>;
  })}</div>;
}

type View = 'walkthrough' | 'replay' | 'video';

function DemoDetail({ demo, view, setView, ...knowledge }: { demo: Demo; view: View; setView: (view: View) => void } & KnowledgeContext) {
  const [data, setData] = useState<DemoData | null>(null), [error, setError] = useState(''), [attempt, setAttempt] = useState(0);
  const [videoError, setVideoError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError('');
    fetch(demo.data, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('The recorded data could not be loaded.');
      const result = await response.json();
      if (result.game !== demo.game || (result.kind === 'voice' ? !Array.isArray(result.calls) : !Array.isArray(result.tasks))) throw new Error('This demo’s recorded data is incomplete.');
      if (!controller.signal.aborted) setData(result);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message || 'The recorded data could not be loaded.'); });
    return () => controller.abort();
  }, [demo, attempt]);
  return <div className={`demo-detail ${view === 'walkthrough' ? 'is-guided' : ''}`}>
    <div className="demo-introduction"><div><span className={`showcase-badge ${demo.placeholder ? 'scripted' : 'recorded'}`}><i />{evidenceLabel(demo)}</span><h2>{demo.title}</h2><p>{view === 'walkthrough' ? demo.description : demo.hook}</p></div><div className="demo-kind"><DemoIcon id={demo.id} /><span>{demo.kind === 'voice' ? 'Voice agent' : demo.kind === 'multi' ? 'Multi-turn agent' : 'Single-turn environment'}</span></div></div>
    {view === 'replay' && <><DemoStats demo={demo} /><div className="showcase-lesson"><span className="lesson-symbol">↳</span><p><strong>The loophole</strong>{demo.loophole}</p><a href="#live">Explore live audits <span>↗</span></a></div></>}
    <div className="replay-view-bar"><div className="showcase-view-tabs" role="group" aria-label="Showcase view"><button aria-pressed={view === 'walkthrough'} onClick={() => setView('walkthrough')}>↗ Guided demo</button><button aria-pressed={view === 'replay'} onClick={() => setView('replay')}>{demo.kind === 'voice' ? '◎ Calls & evidence' : '◫ Interactive replay'}</button><button aria-pressed={view === 'video'} onClick={() => setView('video')}>▷ Watch film</button></div><span>{demo.placeholder ? 'Scripted policies · scores from the real grader' : demo.kind === 'voice' ? 'Recorded calls · synthesized voices' : 'Recorded GPU training · held-out evaluations'}</span></div>
    {view === 'video' ? <section className="showcase-panel showcase-film" aria-label={`${demo.title} video`}><video key={demo.video} controls playsInline preload="metadata" aria-label={`${demo.title} showcase film`} src={demo.video} onError={() => setVideoError(true)} />{videoError && <p role="alert">The film could not be loaded. The recorded replay is still available.</p>}<div><span>{demo.placeholder ? 'SCRIPTED DEMONSTRATION' : demo.kind === 'voice' ? 'RECORDED VOICE AUDIT' : 'RECORDED TRAINING RUN'}</span><p>{demo.placeholder ? 'The film uses the same scripted examples as the replay. These are not trained-model results.' : demo.kind === 'voice' ? 'Cartesia voices read the recorded audit transcripts. The film compares both judges with the policy.' : 'Recorded model rollouts from the GPU runs: base, trained on the loose reward, and trained on the fixed reward.'}</p></div></section> : error ? <div className="showcase-panel showcase-empty" role="alert"><h3>Replay unavailable</h3><p>{error}</p><button onClick={() => setAttempt(value => value + 1)}>Retry loading replay</button></div> : !data ? <div className="showcase-panel showcase-empty" role="status"><span className="loading-pulse" /><p>Loading recorded evidence…</p></div> : view === 'walkthrough' ? <DemoWalkthrough demo={demo} data={data} {...knowledge} /> : data.kind === 'voice' ? <VoiceReplay data={data} /> : <GameReplay demo={demo} data={data} />}
    <div className="showcase-provenance"><p>{demo.placeholder ? 'About these examples: base is a random policy, reward hacked is a scripted exploit, and hardened is the reference solver. No trained-model results are included.' : demo.kind === 'voice' ? 'About this audit: the underlying calls were simulated for the refund-desk experiment and scored against its policy. Playback uses synthesized voices.' : `About these runs: recorded model rollouts from GPU training on the loose and fixed rewards. Means include all ${demo.samples} held-out tasks; the featured task is chosen to show a clear contrast.${demo.shown ? ` ${demo.shown}` : ''}`}</p><details><summary>Source & provenance</summary><p>Imported from <a href={`https://github.com/vsvaidya27/loophole/tree/${sourceRevision}/showcase`} target="_blank" rel="noreferrer">showcase · {sourceRevision.slice(0, 7)} ↗</a></p><code>{demo.source}</code><a href={demo.data} download={`${demo.id}-evidence.json`}>Download recorded data ↓</a></details></div>
  </div>;
}

export function ShowcaseDashboard(knowledge: KnowledgeContext) {
  const [selected, setSelected] = useState(selectedFromHash);
  const [view, setView] = useState<View>('walkthrough');
  useEffect(() => {
    const update = () => {
      const id = selectedFromHash();
      if (window.location.hash.startsWith('#showcase/') && window.location.hash !== `#showcase/${id}`) {
        window.history.replaceState(null, '', `#showcase/${id}`);
      }
      setSelected(id);
    };
    update();
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const demo = demos.find(item => item.id === selected) ?? demos[0];
  return <div className="showcase-dashboard">
    <div className="showcase-page-heading"><div><span className="eyebrow">TASK / ENVIRONMENT / LOOPHOLE / REPAIR / KNOWLEDGE</span><h1>Better environments. Better rewards.</h1><p>Follow a task through its reward failure, a revised environment, and the knowledge it leaves behind.</p></div><div className="showcase-count"><strong>{String(demos.length).padStart(2, '0')}</strong><span>DEMONSTRATIONS</span></div></div>
    <nav className="demo-selector" aria-label="Showcase demos">{demos.map((item, index) => <a href={`#showcase/${item.id}`} key={item.id} aria-current={selected === item.id ? 'page' : undefined} className={`demo-selector-item demo-${item.id}`}><span className="demo-icon"><DemoIcon id={item.id} /></span><span className="demo-selector-copy"><strong>{item.title}</strong>{item.kind === 'voice' && <small>{item.samples} recorded calls</small>}</span><span className="demo-index">0{index + 1}</span></a>)}</nav>
    <DemoDetail key={demo.id} demo={demo} view={view} setView={setView} {...knowledge} />
  </div>;
}

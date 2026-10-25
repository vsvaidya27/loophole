import { useRef, useState } from 'react';
import type { VoiceData, Verdict } from './model';

function JudgeVerdict({ title, verdict, correct }: { title: string; verdict: Verdict; correct: boolean }) {
  const agrees = verdict.success === correct;
  return <div className={`judge-verdict ${agrees ? 'aligned' : 'misaligned'}`}><span className="eyebrow">{title}</span><strong>{verdict.success ? 'PASS' : 'FAIL'} <small>{agrees ? 'Matches the policy' : 'Misses the policy'}</small></strong><p>{verdict.reason}</p></div>;
}

export function VoiceReplay({ data }: { data: VoiceData }) {
  const [callIndex, setCallIndex] = useState(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const call = data.calls[callIndex];
  if (!call) return <p className="showcase-empty">No recorded calls are available.</p>;
  return <section className="showcase-panel voice-section" aria-label="Recorded voice evidence">
    <div className="showcase-section-heading"><div><span className="eyebrow">ONE CALL / TWO JUDGES</span><h3>Listen, then check the verdict</h3><p>Recorded audit transcripts, with synthesized Cartesia voices.</p></div><label className="example-picker">Call<select aria-label="Recorded call" value={callIndex} onChange={event => { audio.current?.pause(); setCallIndex(Number(event.target.value)); }}>{data.calls.map((item, index) => <option key={item.id} value={index}>{index + 1}. {item.honest ? 'Honest agent' : 'Flawed agent'} · {item.correct_action}</option>)}</select></label></div>
    <div className="call-summary"><h4>{call.label}</h4><div><span>Policy requires <strong>{call.correct_action}</strong></span><span>Agent chose <strong>{call.decision}</strong></span><span className={call.true_success ? 'outcome-correct' : 'outcome-wrong'}>{call.true_success ? 'Policy followed' : 'Policy violated'}</span></div></div>
    <div className="voice-evidence-grid">
      <div className="call-transcript" key={call.id}>{call.transcript.map(([who, text], index) => <div className={`transcript-line ${who.toLowerCase()}`} key={index}><div className="speaker-avatar">{who === 'Agent' ? 'A' : 'C'}</div><div><span>{who}<small>Turn {index + 1}</small></span><p>{text}</p>{call.audio?.[index] && <audio aria-label={`${who}, turn ${index + 1}`} controls preload="none" src={call.audio[index]} onPlay={event => { if (audio.current !== event.currentTarget) audio.current?.pause(); audio.current = event.currentTarget; }} />}</div></div>)}</div>
      <div className="judge-comparison"><JudgeVerdict title="Baseline judge" verdict={call.verdicts.baseline} correct={call.true_success} /><JudgeVerdict title="Hardened judge" verdict={call.verdicts.hardened} correct={call.true_success} /><details className="judge-prompts"><summary>Compare the judge prompts</summary><h4>Baseline</h4><pre>{data.judges.baseline}</pre><h4>Hardened</h4><pre>{data.judges.hardened}</pre></details></div>
    </div>
    <p className="replay-footnote">{data.provenance} The aggregate rates above come from the full audit; these five calls are selected examples.</p>
  </section>;
}

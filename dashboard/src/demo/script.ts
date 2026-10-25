import { useCallback, useEffect, useMemo, useState } from 'react';

export type ActId = 1 | 2 | 3 | 4 | 5 | 6;
export const ACTS: { id: ActId; name: string }[] = [
  { id: 1, name: 'The target' }, { id: 2, name: 'The graph remembers' }, { id: 3, name: 'Check the gap' },
  { id: 4, name: 'Adapt the rule' }, { id: 5, name: 'Verify transfer' }, { id: 6, name: 'Watch it learn' },
];

/** One step of the presentation. `ms` 0 means the step ends itself (training) or is the last one. */
export interface Beat { act: ActId; key: string; ms: number; index: number }

export function buildBeats(): Beat[] {
  const beats: Omit<Beat, 'index'>[] = [
    { act: 1, key: 'arrive', ms: 4500 }, { act: 1, key: 'flaw', ms: 6000 },
    { act: 2, key: 'graph', ms: 4000 }, { act: 2, key: 'query', ms: 10000 }, { act: 2, key: 'handoff', ms: 10000 },
    { act: 3, key: 'attack', ms: 6000 }, { act: 3, key: 'scope', ms: 5500 },
    { act: 4, key: 'write', ms: 6500 }, { act: 4, key: 'check', ms: 6500 },
    { act: 5, key: 'valid-play', ms: 7000 }, { act: 5, key: 'publication', ms: 8000 },
    { act: 6, key: 'arena', ms: 4500 }, { act: 6, key: 'train', ms: 0 }, { act: 6, key: 'result', ms: 0 },
  ];
  return beats.map((beat, index) => ({ ...beat, index }));
}

/** How far into its act the presentation is (0 = the act's first beat). */
export function progressIn(beats: Beat[], index: number, act: ActId): number {
  const current = beats[index];
  if (current.act < act) return -1;
  const own = beats.filter(beat => beat.act === act);
  return current.act > act ? own.length - 1 : own.findIndex(beat => beat.index === index);
}

/** Playback state and presenter controls: space, arrows, 1 to 6, R, and S for speed. */
export function usePlayback(beats: Beat[], autoplay = false) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(autoplay);
  const [speed, setSpeed] = useState(1);
  const beat = beats[index];
  const last = beats.length - 1;

  const next = useCallback(() => setIndex(i => Math.min(last, i + 1)), [last]);
  const back = useCallback(() => setIndex(i => Math.max(0, i - 1)), []);
  const jump = useCallback((act: ActId) => setIndex(beats.findIndex(b => b.act === act)), [beats]);
  const restart = useCallback(() => { setIndex(0); setPlaying(true); }, []);

  useEffect(() => {
    if (playing && index === last) { setPlaying(false); return; }
    if (!playing || beat.ms === 0) return;
    const timer = window.setTimeout(next, beat.ms / speed);
    return () => window.clearTimeout(timer);
  }, [playing, index, last, beat, speed, next]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)) return;
      if (event.key === ' ') { event.preventDefault(); setPlaying(p => !p); }
      else if (event.key === 'ArrowRight') next();
      else if (event.key === 'ArrowLeft') back();
      else if (event.key === 'r' || event.key === 'R') restart();
      else if (event.key === 's' || event.key === 'S') setSpeed(s => (s === 1 ? 2 : 1));
      else if (/^[1-6]$/.test(event.key)) jump(Number(event.key) as ActId);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [next, back, restart, jump]);

  return useMemo(() => ({ index, beat, playing, speed, setPlaying, setSpeed, next, back, jump, restart }),
    [index, beat, playing, speed, next, back, jump, restart]);
}

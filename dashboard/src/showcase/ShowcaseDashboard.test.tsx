// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ShowcaseDashboard } from './ShowcaseDashboard';
import { demos, featuredTask, type GameData } from './model';
import trading from '../../public/showcase/data/trading.json';
import webagent from '../../public/showcase/data/webagent.json';
import voice from '../../public/showcase/data/voice.json';

let container: HTMLDivElement, root: Root;
const fixtures: Record<string, unknown> = { trading, webagent, voice };
const readDemo = (id: string) => JSON.parse(JSON.stringify(fixtures[id]));
const successfulFetch = async (url: string) => ({ ok: true, json: async () => readDemo(url.split('/').at(-1)!.replace('.json', '')) });
const node = <T extends Element = HTMLElement>(selector: string) => {
  const result = container.querySelector<T>(selector);
  expect(result, selector).not.toBeNull();
  return result!;
};
const button = (text: string) => {
  const result = Array.from(container.querySelectorAll('button')).find(item => item.textContent === text);
  expect(result, text).toBeDefined();
  return result!;
};
const click = (element: Element) => act(() => { element.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
const navigate = async (id: string) => {
  await act(async () => {
    window.history.replaceState(null, '', `#showcase/${id}`);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  });
};

beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  window.history.replaceState(null, '', '#showcase/trading');
  vi.stubGlobal('fetch', vi.fn(successfulFetch));
  container = document.createElement('div'); document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<StrictMode><ShowcaseDashboard /></StrictMode>));
  expect(button('↗ Guided demo').getAttribute('aria-pressed')).toBe('true');
  await click(button('◫ Interactive replay'));
});

afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  vi.useRealTimers(); vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

describe('Showcase dashboard', () => {
  it('preserves trained-run provenance, aggregate scores, and navigation to the three demos', async () => {
    expect(container.textContent).toContain('Recorded training run');
    expect(container.textContent).toContain('Trained on fixed reward');
    expect(node('.showcase-stats .policy-hacked').textContent).toContain('100%');
    expect(node('.showcase-stats .policy-hardened').textContent).toContain('50%');
    const hackedReplay = node('.policy-replay.policy-hacked');
    expect(hackedReplay.textContent).toContain('100%');
    expect(hackedReplay.textContent).toContain('Reward exceeds the true score');
    expect(container.textContent).toContain('Means include all 24 held-out tasks');
    expect(container.textContent).not.toContain('Reference solver');
    expect(node<HTMLSelectElement>('[aria-label="Replay example"]').value).toBe('1');
    expect(container.querySelectorAll('.demo-selector a')).toHaveLength(3);
    expect(node('.showcase-count strong').textContent).toBe('03');
    for (const retired of ['snake', 'lights_out']) {
      await navigate(retired);
      expect(window.location.hash).toBe('#showcase/trading');
      expect(node<HTMLAnchorElement>('.demo-selector a[aria-current]').hash).toBe('#showcase/trading');
    }
  });

  it('advances recorded frames, ends playback, and restarts without changing final scores', async () => {
    vi.useFakeTimers();
    expect(node('.policy-hardened .order-label').textContent).toBe('Waiting for order');
    await click(node('[aria-label="Next replay step"]'));
    expect(node('[aria-label="Current replay step"]').textContent).toBe('1 / 3');
    expect(node('.policy-hardened .order-label').textContent).toBe('SELL 5');
    await click(button('▶ Play replay'));
    await act(() => vi.advanceTimersByTime(700));
    await act(() => vi.advanceTimersByTime(700));
    expect(node('[aria-label="Current replay step"]').textContent).toBe('3 / 3');
    expect(node<HTMLButtonElement>('[aria-label="Next replay step"]').disabled).toBe(true);
    expect(button('▶ Play replay')).toBeDefined();
    expect(node('.policy-hardened .frame-caption').textContent).toBe('Future price revealed');
    expect(node('.policy-hardened .price-chart').textContent).toContain('90');
    expect(node('.policy-hacked .order-label').textContent).toContain('BUY 7, SELL 7');
    await click(node('[aria-label="Restart replay"]'));
    expect(node('[aria-label="Current replay step"]').textContent).toBe('0 / 3');
    expect(node('.policy-replay.policy-hacked .replay-scores').textContent).toContain('Loose reward100%');
  });

  it('stops the old timer and resets playback when changing examples', async () => {
    vi.useFakeTimers();
    await click(button('▶ Play replay'));
    const picker = node<HTMLSelectElement>('[aria-label="Replay example"]');
    await act(() => { picker.value = '0'; picker.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(() => vi.advanceTimersByTime(5000));
    expect(node('[aria-label="Current replay step"]').textContent).toMatch(/^0 \/ /);
    expect(button('▶ Play replay')).toBeDefined();
  });

  it('loads every game and isolates recorded web pages from scripts and network access', async () => {
    expect(container.querySelectorAll('.price-chart')).toHaveLength(3);
    await navigate('webagent');
    expect(node('.demo-introduction h2').textContent).toBe('Computer use');
    const frame = node<HTMLIFrameElement>('iframe');
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(frame.srcdoc).toContain("default-src 'none'");
    expect(frame.srcdoc).toContain("form-action 'none'");
    await click(node('[aria-label="Next replay step"]'));
    expect(node('.policy-hardened .frame-caption').textContent).toContain('click 1');
    expect(node<HTMLSelectElement>('[aria-label="Replay example"]').value).toBe('7');
  });

  it('shows recorded voice verdicts, selected calls, and separate full-audit rates', async () => {
    await navigate('voice');
    expect(container.textContent).toContain('Recorded audit');
    expect(container.textContent).not.toContain('Scripted example');
    expect(node('.showcase-stats').textContent).toContain('25%→0%');
    expect(node('.judge-verdict.misaligned').textContent).toContain('PASS');
    expect(node('.judge-verdict.aligned').textContent).toContain('FAIL');
    expect(container.querySelectorAll('audio')).toHaveLength(4);
    expect(node<HTMLAudioElement>('audio').getAttribute('src')).toMatch(/^\/showcase\/audio\/voice-0-0.mp3$/);
    const picker = node<HTMLSelectElement>('[aria-label="Recorded call"]');
    await act(() => { picker.value = '3'; picker.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(node('.call-summary').textContent).toContain('Policy followed');
    expect(container.querySelectorAll('.judge-verdict.aligned')).toHaveLength(2);
    expect(container.textContent).toContain('these five calls are selected examples');
  });

  it('uses the matching video and stops replay playback while the film view is active', async () => {
    vi.useFakeTimers();
    await click(button('▶ Play replay'));
    await click(button('▷ Watch film'));
    expect(node<HTMLVideoElement>('video').getAttribute('src')).toBe('/showcase/videos/trading.mp4');
    expect(node<HTMLVideoElement>('video').autoplay).toBe(false);
    expect(container.querySelector('[aria-label="Current replay step"]')).toBeNull();
    await act(() => vi.advanceTimersByTime(5000));
    await click(button('◫ Interactive replay'));
    expect(node('[aria-label="Current replay step"]').textContent).toBe('0 / 3');
  });

  it('offers retry on failed data loads and does not display the previous demo as new data', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('Offline'));
    await navigate('webagent');
    expect(node('[role="alert"]').textContent).toContain('Offline');
    expect(container.querySelector('.policy-replays')).toBeNull();
    vi.stubGlobal('fetch', vi.fn(successfulFetch));
    await click(button('Retry loading replay'));
    expect(node('iframe')).toBeDefined();
  });

  it('keeps catalog metrics and declared provenance in agreement with source artifacts', () => {
    for (const demo of demos) {
      const data = readDemo(demo.id);
      expect(demo.placeholder).toBe(data.placeholder);
      expect(demo.samples).toBe((data.tasks ?? data.calls).length);
      if (demo.kind === 'voice') continue;
      const game = data as GameData;
      for (const [policy, score] of Object.entries(demo.scores)) {
        const mean = game.tasks.reduce((sum, task) => sum + task.rollouts[policy as keyof typeof task.rollouts].strict, 0) / game.tasks.length;
        expect(score!.strict).toBeCloseTo(mean);
      }
      expect(featuredTask(game.tasks)).toBeGreaterThanOrEqual(0);
    }
  });

  it('walks from the task through a loophole to the repaired environment and an inspectable evidence graph', async () => {
    await click(button('↗ Guided demo'));
    expect(node('.story-heading h3').textContent).toBe('Start with the task.');
    expect(node('.task-brief').textContent).toContain('109, 108, 106');
    expect(container.querySelector('.loophole-metrics')).toBeNull();
    await click(button('Next: RL environment →'));
    expect(node('[aria-label="Original RL environment"]').textContent).toContain('Reward feeds the next policy update');
    await click(button('Next: Reward loophole →'));
    expect(node('.loophole-metrics').textContent).toContain('Original reward100%');
    expect(node('.loophole-metrics').textContent).toContain('True task score0%');
    await click(button('Next: Improved environment →'));
    expect(node('.same-exploit').textContent).toContain('Original100%→Revised0%');
    expect(node('.positive-check').textContent).toContain('23% → 50%');
    expect(node('.preserved-state').textContent).toContain('Same task');
    expect(node('.story-episode-label').textContent).toContain('Trained on the fixed reward');
    await click(button('Next: Knowledge graph →'));
    expect(container.querySelectorAll('.lineage-node')).toHaveLength(6);
    const failure = node('[aria-label="Inspect Reward loophole"]');
    await act(() => failure.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(node('.lineage-inspector').textContent).toContain('Multiple, oversized trades');
    await click(button('Show recorded graph ↓'));
    expect(node('.story-graph-empty').textContent).toContain('No knowledge records are available');
    await click(button('↺ Restart demo'));
    expect(node('.story-heading h3').textContent).toBe('Start with the task.');
  });

  it('stops the guided episode when moving to another step or switching demos', async () => {
    vi.useFakeTimers();
    await click(button('↗ Guided demo'));
    await click(button('Next: RL environment →'));
    await click(button('Next: Reward loophole →'));
    await click(button('▶ Play episode'));
    await act(() => vi.advanceTimersByTime(1100));
    expect(node('[aria-label="Episode position"]').textContent).toBe('1 / 3');
    await click(button('Next: Improved environment →'));
    await act(() => vi.advanceTimersByTime(5000));
    expect(node('[aria-label="Episode position"]').textContent).toBe('0 / 3');
    await navigate('voice');
    expect(node('.story-heading h3').textContent).toBe('Start with the task.');
  });

  it('shows the recorded voice judge repair without claiming a retrained agent', async () => {
    await navigate('voice');
    await click(button('↗ Guided demo'));
    await click(button('Next: RL environment →'));
    await click(button('Next: Reward loophole →'));
    expect(node('.loophole-metrics').textContent).toContain('Original judgePASS');
    expect(node('.loophole-metrics').textContent).toContain('Policy requiresDENY');
    expect(node<HTMLAudioElement>('audio').getAttribute('src')).toBe('/showcase/audio/voice-0-0.mp3');
    await click(button('Next: Improved environment →'));
    expect(node('.same-exploit').textContent).toContain('OriginalPASS→RevisedFAIL');
    expect(node('.positive-check').textContent).toContain('25% → 0%');
    expect(container.textContent).toContain('It does not show a retrained voice agent.');
  });

  it('replays the distinct strict and loose web episodes and resets when switching environments', async () => {
    await navigate('webagent');
    const mode = node<HTMLSelectElement>('[aria-label="Replay environment"]');
    const slider = node<HTMLInputElement>('[aria-label="Replay step"]');
    await act(() => { slider.value = '3'; slider.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(() => { mode.value = 'loose'; mode.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(node('[aria-label="Current replay step"]').textContent).toBe('0 / 8');
    const picker = node<HTMLSelectElement>('[aria-label="Replay example"]');
    await act(() => { picker.value = '7'; picker.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(node<HTMLIFrameElement>('.policy-hardened iframe').srcdoc).toContain(webagent.tasks[7].rollouts.hardened.loose_pages[0]);
    expect(container.textContent).toContain('Separate recorded episodes');
  });
});

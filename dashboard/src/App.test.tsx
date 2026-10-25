// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Timestamp } from 'spacetimedb';
import { App } from './App';
import { connectLive, type LiveHandlers, type LiveSnapshot } from './live';
import voice from '../public/showcase/data/voice.json';

vi.mock('./live', async importOriginal => ({
  ...await importOriginal<typeof import('./live')>(),
  connectLive: vi.fn(),
}));

function sample(): LiveSnapshot {
  const time = new Timestamp(0n);
  const invariants = [{ invariantId: 'failure-one', envId: 'game/ai-source', exploitId: 'exploit-one', exploitClass: 'answer-parsing', title: 'Multiple accepted answers', mechanism: 'The grader accepts any matching answer.', rootCause: 'Unanchored answer matching.', preconditions: 'The task expects a single answer.', defensePattern: 'Require exactly one answer.', evidencePath: 'runs/source/evidence.json', createdAt: time }];
  const exploits = [{ invariantId: 'failure-one', envId: 'game/ai-source', exploitId: 'exploit-one', exploitClass: 'answer-parsing', iteration: 1, summary: 'A conflicting answer earns reward.', sampleCompletion: '<answer>7 or 9</answer>', rewardOriginal: 1, rewardPatched: undefined, status: 'confirmed', evidencePath: 'runs/source/evidence.json', confirmedAt: time }];
  const applications = [{ applicationKey: 'source-to-target', runId: 'transfer-one', invariantId: 'failure-one', targetEnvId: 'target', outcome: 'blocked', detail: '{"reward":0}', createdAt: time }];
  return {
    rows: {
      environments: [{ envId: 'game/ai-source', title: 'Source arithmetic', source: 'generated', status: 'hardening' }, { envId: 'target', title: 'Target task', source: 'registry', status: 'patched' }],
      invariants, exploits, ruleApplications: applications,
      rules: [{ ruleId: 'answer-parsing', title: 'Answer parsing', memberCount: 1, envCount: 1 }], similarityEdges: [],
    },
    invariants, exploits, applications,
  };
}

let container: HTMLDivElement;
let root: Root | undefined;
let sessions: { handlers: LiveHandlers; stop: ReturnType<typeof vi.fn> }[];
let observers: { disconnect: ReturnType<typeof vi.fn> }[];
const current = () => sessions[sessions.length - 1];
const element = <T extends Element = HTMLElement>(selector: string) => {
  const node = container.querySelector<T>(selector);
  expect(node, selector).not.toBeNull();
  return node!;
};
const button = (text: string) => {
  const node = Array.from(container.querySelectorAll('button')).find(node => node.textContent === text);
  expect(node, text).toBeDefined();
  return node!;
};
const click = async (node: Element) => act(() => { node.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
const publish = async (snapshot = sample()) => act(() => { current().handlers.status('live'); current().handlers.snapshot(snapshot); });

beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  observers = [];
  vi.stubGlobal('ResizeObserver', class {
    disconnect = vi.fn();
    observe = vi.fn();
    constructor() { observers.push(this); }
  });
  sessions = [];
  vi.mocked(connectLive).mockReset().mockImplementation(handlers => {
    const stop = vi.fn();
    sessions.push({ handlers, stop });
    handlers.status('connecting');
    return stop;
  });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(() => root!.render(<StrictMode><App /></StrictMode>));
});

afterEach(async () => {
  if (root) await act(() => root!.unmount());
  container.remove();
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

describe('React live dashboard', () => {
  it('waits for records and displays initial connection errors without inventing totals', async () => {
    expect(element('#status').textContent).toBe('Connecting');
    expect(container.querySelector('.metric')).toBeNull();
    await act(() => current().handlers.status('error', 'Service unreachable'));
    expect(element('#status').textContent).toBe('Live connection failed');
    expect(element('[role="alert"]').textContent).toBe('Service unreachable');
    expect(container.querySelector('.network-node')).toBeNull();
    await publish();
    expect(element('#status').textContent).toBe('Live subscription');
    expect(Array.from(container.querySelectorAll('.metric strong'), node => node.textContent)).toEqual(['2', '1', '1', '1']);
    expect(container.querySelectorAll('.network-node')).toHaveLength(4);
    expect(container.querySelectorAll('.network-edge')).toHaveLength(3);
  });

  it('cleans up Strict Mode subscriptions and observers, ignores late callbacks, and disconnects on unmount', async () => {
    expect(sessions).toHaveLength(2);
    expect(sessions[0].stop).toHaveBeenCalledOnce();
    expect(current().stop).not.toHaveBeenCalled();
    await act(() => sessions[0].handlers.snapshot(sample()));
    expect(container.querySelector('.metric')).toBeNull();
    await publish();
    await act(() => root!.unmount());
    root = undefined;
    for (const session of sessions) expect(session.stop).toHaveBeenCalledOnce();
    for (const observer of observers) expect(observer.disconnect).toHaveBeenCalledOnce();
    const count = sessions.length;
    await act(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
    expect(sessions).toHaveLength(count);
  });

  it('keeps records during reconnect and rejects events from the previous connection', async () => {
    await publish();
    const previous = current();
    await act(() => previous.handlers.status('disconnected', 'Connection closed'));
    expect(element('#status').textContent).toContain('may be stale');
    await click(button('Reconnect'));
    expect(previous.stop).toHaveBeenCalledOnce();
    expect(element('#status').textContent).toContain('Reconnecting');
    expect(container.querySelectorAll('.network-node')).toHaveLength(4);
    await act(() => { previous.handlers.status('error', 'Obsolete error'); previous.handlers.snapshot({ ...sample(), invariants: [] }); });
    expect(element('#status').textContent).toContain('Reconnecting');
    expect(element('#error').textContent).toBe('');
    await publish();
    expect(element('#status').textContent).toBe('Live subscription');
  });

  it('reconnects when a page returns from the back-forward cache', async () => {
    await publish();
    const previous = current();
    await act(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })));
    expect(previous.stop).toHaveBeenCalledOnce();
    expect(element('#status').textContent).toContain('Disconnected');
    await act(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
    expect(current()).not.toBe(previous);
    await publish();
    expect(element('#status').textContent).toBe('Live subscription');
  });

  it('selects SVG nodes by keyboard, preserves focus and the evidence tab during live updates', async () => {
    await publish();
    const node = element<SVGElement>('[data-node-id="inv:failure-one"]');
    node.focus();
    await act(() => node.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(node.getAttribute('aria-pressed')).toBe('true');
    expect(document.activeElement).toBe(node);
    expect(element('pre').textContent).toBe('<answer>7 or 9</answer>');
    expect(container.querySelector('answer')).toBeNull();
    expect(element('.patched strong').textContent).toBe('Not recorded');
    const failure = button('Failure');
    failure.focus();
    await act(() => failure.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })));
    const defense = button('Defense');
    expect(document.activeElement).toBe(defense);
    expect(defense.getAttribute('aria-selected')).toBe('true');
    const snapshot = sample();
    snapshot.invariants[0].defensePattern = 'Reject multiple answer tokens.';
    const sessionCount = sessions.length;
    element('#graph').scrollTop = 120;
    await publish(snapshot);
    expect(element('[data-node-id="inv:failure-one"]')).toBe(node);
    expect(document.activeElement).toBe(defense);
    expect(element('[role="tabpanel"]').textContent).toContain('Reject multiple answer tokens.');
    expect(element('#graph').scrollTop).toBe(120);
    expect(sessions).toHaveLength(sessionCount);
    await act(() => defense.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })));
    expect(button('Transfer (1)').getAttribute('aria-selected')).toBe('true');
    expect(element('.transfer-card').textContent).toContain('Target task');
  });

  it('navigates environments, rule families, and transfer targets without hiding the graph', async () => {
    await publish();
    await click(element('[data-node-id="rule:answer-parsing"]'));
    expect(element('#selection-kind').textContent).toBe('Rule family');
    await click(button('Multiple accepted answers'));
    await click(button('Transfer (1)'));
    await click(button('Inspect target environment →'));
    expect(element('#selection-kind').textContent).toBe('Environment');
    expect(element<HTMLSelectElement>('#environment-focus').value).toBe('env:target');
    await click(button('blocked · Multiple accepted answers'));
    expect(button('Transfer (1)').getAttribute('aria-selected')).toBe('true');
    const picker = element<HTMLSelectElement>('#environment-focus');
    await act(() => { picker.value = 'env:game/ai-source'; picker.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(element('#details').textContent).toContain('Source arithmetic');
    expect(container.querySelectorAll('.network-node')).toHaveLength(4);
    await click(button('Reset focus'));
    expect(element('#selection-kind').textContent).toBe('No selection');
    expect(picker.value).toBe('');
  });

  it('clears a deleted selection and shows the connected empty state', async () => {
    await publish();
    await click(element('[data-node-id="inv:failure-one"]'));
    const empty: LiveSnapshot = { rows: { environments: [], invariants: [], exploits: [], rules: [], similarityEdges: [], ruleApplications: [] }, invariants: [], exploits: [], applications: [] };
    await publish(empty);
    expect(element('#selection-kind').textContent).toBe('No selection');
    expect(element('#empty').textContent).toContain('Connected. No knowledge records');
    await publish();
    expect(element('#selection-kind').textContent).toBe('No selection');
  });

  it('returns from Showcase with the same live subscription and selected evidence', async () => {
    await publish();
    await click(element('[data-node-id="inv:failure-one"]'));
    await click(button('Defense'));
    const count = sessions.length;
    const selectedNode = element('[data-node-id="inv:failure-one"]');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    await act(async () => {
      window.history.replaceState(null, '', '#showcase/voice');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    expect(element('nav[aria-label="Main navigation"] a[aria-current]').textContent).toBe('Showcase');
    expect(container.querySelector('.showcase-dashboard')).not.toBeNull();
    await act(() => {
      window.history.replaceState(null, '', '#network');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    expect(element('nav[aria-label="Main navigation"] a[aria-current]').textContent).toBe('Knowledge graph');
    expect(element('[data-node-id="inv:failure-one"]')).toBe(selectedNode);
    expect(button('Defense').getAttribute('aria-selected')).toBe('true');
    expect(sessions).toHaveLength(count);
  });

  it('opens evidence from the guided demo’s live graph using the existing subscription', async () => {
    await publish();
    const count = sessions.length;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => voice }));
    await act(async () => {
      window.history.replaceState(null, '', '#showcase/voice');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    await click(button('05Knowledge graph'));
    await click(button('Show recorded graph ↓'));
    expect(container.querySelectorAll('#graph')).toHaveLength(1);
    expect(container.querySelectorAll('#showcase-network .network-node')).toHaveLength(4);
    await click(element('#showcase-network [data-node-id="inv:failure-one"]'));
    await act(() => window.dispatchEvent(new HashChangeEvent('hashchange')));
    expect(window.location.hash).toBe('#network');
    expect(element('#details').textContent).toContain('Multiple accepted answers');
    expect(button('Failure').getAttribute('aria-selected')).toBe('true');
    expect(sessions).toHaveLength(count);
  });
});

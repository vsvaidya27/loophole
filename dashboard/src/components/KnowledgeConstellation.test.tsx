// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildGraph } from '../graph/buildGraph';
import { KnowledgeConstellation } from './KnowledgeConstellation';

const rows = {
  environments: [{ envId: 'a', title: 'Env A', source: 'hub', status: 'patched' }, { envId: 'b', title: 'Env B', source: 'hub', status: 'patched' }],
  invariants: [
    { invariantId: 'a1', envId: 'a', exploitClass: 'multi-answer', title: 'A one' },
    { invariantId: 'a2', envId: 'a', exploitClass: 'parser-bypass', title: 'A two' },
    { invariantId: 'b1', envId: 'b', exploitClass: 'multi-answer', title: 'B one' },
    { invariantId: 'b2', envId: 'b', exploitClass: 'other', title: 'B two' },
  ],
  exploits: [],
  rules: [{ ruleId: 'multi-answer', title: 'Multi answer', memberCount: 2, envCount: 2 }, { ruleId: 'parser-bypass', title: 'Parser bypass', memberCount: 1, envCount: 1 }, { ruleId: 'other', title: 'Other', memberCount: 1, envCount: 1 }],
  similarityEdges: [{ edgeId: 'e1', aId: 'a1', bId: 'b1', score: 0.9 }],
  ruleApplications: [],
};

let container: HTMLDivElement, root: Root;
const render = (selected?: string, onSelect = vi.fn()) => act(() => root.render(<KnowledgeConstellation graph={buildGraph(rows)} selected={selected} onSelect={onSelect} />));
const ids = (selector: string) => Array.from(container.querySelectorAll(selector), node => node.getAttribute('data-constellation-id'));

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe('KnowledgeConstellation', () => {
  it('draws every invariant once, grouped into its rule family, with nothing highlighted', async () => {
    await render();
    expect(ids('.kg-dot')).toHaveLength(4);
    expect(container.querySelectorAll('.kg-family')).toHaveLength(3);
    expect(container.querySelector('.kg-beams')).toBeNull();
  });

  it('highlights an environment’s own rules and only recorded similar records from elsewhere', async () => {
    await render('env:a');
    expect(ids('.kg-dot.picked').sort()).toEqual(['inv:a1', 'inv:a2']);
    expect(ids('.kg-dot.related')).toEqual(['inv:b1']);
    expect(container.querySelectorAll('.kg-beam:not(.related)')).toHaveLength(2);
    expect(container.querySelector('.kg-centre-title')?.textContent).toBe('Env A');
  });

  it('selects a rule family and an invariant through the same callback as the network', async () => {
    const onSelect = vi.fn();
    await render('rule:multi-answer', onSelect);
    expect(ids('.kg-dot.picked').sort()).toEqual(['inv:a1', 'inv:b1']);
    await act(() => { container.querySelector('[data-constellation-id="inv:b2"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await act(() => { container.querySelector('.kg-family[aria-label^="Rule family: Several answers"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
    expect(onSelect.mock.calls).toEqual([['inv:b2'], ['rule:multi-answer']]);
  });
});

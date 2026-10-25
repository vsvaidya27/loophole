// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import snake from '../../public/showcase/data/snake.json';
import { presentSnakePage } from './snakeReplay';

const task = snake.tasks[0];
const render = (html: string) => new DOMParser().parseFromString(presentSnakePage(html)!, 'text/html');
const kinds = (page: Document) => Array.from(page.querySelectorAll('.snake-grid i'), cell => cell.className);

describe('Recorded snake presentation', () => {
  it('keeps the recorded board, turn and food count, with no outcome before the end', () => {
    const page = render(task.rollouts.hardened.pages[0]);
    expect(kinds(page)).toHaveLength(36);
    expect(kinds(page).filter(kind => kind === 'snake-head')).toHaveLength(1);
    expect(kinds(page).filter(kind => kind === 'snake-food')).toHaveLength(1);
    expect(page.querySelector('.snake-board-heading span')?.textContent).toContain('Turn 0/14');
    expect(page.querySelector('.shop-bag span')?.textContent).toBe('0/1');
    expect(page.querySelector('.shop-outcome')).toBeNull();
  });

  it('shows each policy\'s recorded outcome on its final board', () => {
    const last = (policy: 'base' | 'hacked' | 'hardened') => render(task.rollouts[policy].pages.at(-1)!);
    expect(last('hardened').querySelector('.shop-outcome.is-correct')?.textContent).toContain('Ate all the food');
    expect(last('hardened').querySelector('.shop-bag span')?.textContent).toBe('1/1');
    expect(last('base').querySelector('.shop-outcome.is-incorrect')?.textContent).toContain('Crashed');
    expect(last('hacked').querySelector('.shop-outcome.is-incorrect')?.textContent).toContain('Out of turns');
  });

  it('leaves other captured pages alone', () => {
    expect(presentSnakePage('<div class="wf"><em>Shop</em></div>')).toBeNull();
  });
});

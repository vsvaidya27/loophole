export { default as snakeStyles } from './snakeReplay.css?raw';

const escape = (value: string) => value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
const snakeMark = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 18h5v-6h6V7"/><circle cx="17" cy="18" r="1.6" fill="currentColor" stroke="none"/></svg>';
const foodIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="12" cy="13" r="7"/><path d="M12 6c0-2 1-3 3-3"/></svg>';
const cellKinds: Record<string, string> = { h: 'head', b: 'body', f: 'food', e: 'empty' };

/** Present a recorded Snake board in the shop replay's format, without changing the board,
 * the turn, the food count, the last move or the outcome. */
export function presentSnakePage(html: string): string | null {
  const document = new DOMParser().parseFromString(html, 'text/html');
  const root = document.querySelector('.sn');
  const grid = root?.querySelector('.sn-grid');
  if (!root || !grid) return null;
  const [turn, food, last] = Array.from(root.querySelectorAll('.sn-bar span'), span => span.textContent ?? '');
  const eaten = food?.match(/(\d+)\/(\d+)/);
  const cells = Array.from(grid.querySelectorAll('i'), cell => cellKinds[cell.className] ?? 'empty');
  const size = Math.round(Math.sqrt(cells.length));
  if (!turn || !eaten || !cells.length || size * size !== cells.length) return null;
  const end = root.querySelector('.sn-end');
  const won = end?.classList.contains('ok');
  return `<main class="shop-replay snake-replay">
    <header class="shop-header"><div class="shop-brand"><span class="shop-brand-mark snake-mark">${snakeMark}</span><div><strong>Snake</strong><small>${size} × ${size} BOARD · ONE MOVE PER TURN</small></div></div><div class="shop-bag" aria-label="Food eaten">${foodIcon}<span>${escape(eaten[1])}/${escape(eaten[2])}</span></div></header>
    <div class="shop-task"><span>YOUR TASK</span><p>Steer the snake to the food without hitting a wall or its own body.</p></div>
    <section class="snake-board" aria-label="Board"><div class="snake-board-heading"><h2>The board</h2><span>${escape(turn)} · ${escape(last ?? '')}</span></div>
      <div class="snake-grid" style="--n:${size}">${cells.map(kind => `<i class="snake-${kind}"></i>`).join('')}</div>
      <div class="snake-legend"><span><i class="snake-head"></i>Head</span><span><i class="snake-body"></i>Body</span><span><i class="snake-food"></i>Food</span></div>
    </section>
    ${end ? `<div class="shop-outcome ${won ? 'is-correct' : 'is-incorrect'}"><span>${won ? '✓' : '!'}</span><p>${escape(end.textContent ?? '')}</p></div>` : ''}
    <footer class="shop-recording"><span class="shop-recording-dot"></span>Recorded game state<span>Moves match the replay</span></footer>
  </main>`;
}

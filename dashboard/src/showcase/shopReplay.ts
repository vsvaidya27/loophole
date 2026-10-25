export { default as shopStyles } from './shopReplay.css?raw';

const escape = (value: string) => value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
const money = (value: number) => `$${value.toFixed(2)}`;
const bag = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M5 8h14l1 13H4L5 8Z"/><path d="M8 9V6a4 4 0 0 1 8 0v3"/></svg>';

function productArt(name: string, index: number) {
  const illustrations: Record<string, string> = {
    Notebook: '<path d="M41 21 93 13 103 77 51 87Z" fill="#1d3744"/><path d="m47 27 51-8 9 59-51 9Z" fill="#dce5d9"/><path d="m39 18 52-8 10 65-52 8Z" fill="url(#cover)"/><path d="m47 17 10 64" stroke="#95c7b9" stroke-width="2"/><path d="m59 34 25-4m-23 9 20-3" stroke="#bbe0d3" stroke-opacity=".6" stroke-width="2"/><path d="m85 72 3 18 4-5 4 4-3-18" fill="#d4b47d"/>',
    'USB hub': '<path d="M86 37c10-20 34-17 32-1-2 11-18 9-20 18" fill="none" stroke="#758899" stroke-width="4"/><path d="m31 36 57-9 12 39-57 11Z" fill="#78909e"/><path d="m31 36 57-9 4 28-57 11Z" fill="url(#metal)"/><path d="m35 66 57-11 8 11-57 11Z" fill="#344a5a"/><path d="m42 63 10-2 2 5-10 2m16-9 10-2 2 5-10 2m16-9 10-2 2 5-10 2" stroke="#a4c0c5" stroke-width="1.5" fill="#152533"/><circle cx="75" cy="40" r="2" fill="#a9e2c6"/>',
    'Desk lamp': '<ellipse cx="70" cy="83" rx="27" ry="5" fill="#735a3b"/><path d="M48 79h43l5 5H44Z" fill="#d4bb85"/><path d="m71 78-13-25 23-23" fill="none" stroke="#c8ad75" stroke-width="5" stroke-linejoin="round"/><circle cx="58" cy="53" r="4" fill="#e6d29f"/><path d="m76 24 15 5 9 19-38-13Z" fill="url(#gold)"/><path d="m62 35 38 13" stroke="#f5e8bd" stroke-width="3"/><path d="m66 39 30 12-8 23H48Z" fill="#ecdba9" opacity=".07"/>',
    Headphones: '<path d="M37 59V44a33 33 0 0 1 66 0v15" fill="none" stroke="#93a6b7" stroke-width="9"/><path d="M37 58V44a33 33 0 0 1 66 0v14" fill="none" stroke="#415b70" stroke-width="4"/><rect x="29" y="48" width="22" height="36" rx="10" fill="url(#metal)"/><rect x="89" y="48" width="22" height="36" rx="10" fill="url(#metal)"/><path d="M45 56v20m50-20v20" stroke="#a5bac4" stroke-width="3" stroke-linecap="round"/>',
    'Mouse pad': '<path d="m24 36 76-15 18 47-76 16Z" fill="#374052"/><path d="m26 34 75-14 17 44-75 16Z" fill="url(#cover)"/><path d="m31 37 67-13 14 37-67 14Z" fill="none" stroke="#8db8ae" stroke-opacity=".45"/><path d="m65 41 18-3m-17 8 18-3" stroke="#b2cfc0" stroke-width="1.5"/>',
    'Water bottle': '<rect x="57" y="13" width="26" height="13" rx="4" fill="#bacab9"/><path d="M58 26h24v8l7 9v36a8 8 0 0 1-8 8H59a8 8 0 0 1-8-8V43l7-9Z" fill="url(#cover)"/><path d="M59 47v28" stroke="#afd6bf" stroke-width="3" stroke-linecap="round" opacity=".5"/><path d="M61 17h18" stroke="#e4e6d4" stroke-width="2"/>',
  };
  const drawing = illustrations[name] ?? '<path d="m40 31 32-14 31 15v41L72 89 40 73Z" fill="url(#cover)"/><path d="m40 31 32 15 31-14M72 46v43" fill="none" stroke="#9bc4b6"/>';
  return `<svg class="shop-product-art" viewBox="0 0 140 105" role="img" aria-label="${escape(name)} illustration"><defs><linearGradient id="cover-${index}" x2="1" y2="1"><stop stop-color="#81b8a4"/><stop offset="1" stop-color="#365f5b"/></linearGradient><linearGradient id="metal-${index}" x2="1" y2="1"><stop stop-color="#b6c8cd"/><stop offset="1" stop-color="#586f82"/></linearGradient><linearGradient id="gold-${index}" x2="1" y2="1"><stop stop-color="#e3c995"/><stop offset="1" stop-color="#917340"/></linearGradient></defs><ellipse cx="72" cy="94" rx="39" ry="5" fill="#050a0e" opacity=".25"/>${drawing.replace(/url\(#(cover|metal|gold)\)/g, `url(#$1-${index})`)}</svg>`;
}

/** Restyle a captured shop state without changing its inventory, actions, cart, or verdict. */
export function presentShopPage(html: string): string | null {
  const document = new DOMParser().parseFromString(html, 'text/html');
  if (document.querySelector('.wf-bar em')?.textContent !== 'Shop') return null;
  const rows = Array.from(document.querySelectorAll('.wf-row'));
  const products = rows.flatMap(row => {
    const match = row.querySelector('.wf-btn')?.textContent?.match(/^Add to cart: (.+) \(\$(\d+(?:\.\d+)?)\)$/);
    return match ? [{ name: match[1], price: Number(match[2]), id: row.querySelector('b')?.textContent ?? '', active: row.classList.contains('hot') }] : [];
  });
  const checkout = rows.find(row => row.querySelector('.wf-btn')?.textContent === 'Checkout');
  const ad = rows.find(row => row.querySelector('.wf-ad'));
  const cartText = document.querySelector('.wf-cart')?.textContent?.replace(/^Cart:\s*/, '');
  if (!products.length || !checkout || cartText === undefined) return null;
  const cart = cartText === 'empty' ? [] : cartText.split(', ');
  if (cart.some(name => !products.some(product => product.name === name))) return null;
  const quantities = new Map<string, number>();
  for (const name of cart) quantities.set(name, (quantities.get(name) ?? 0) + 1);
  const total = cart.reduce((sum, name) => sum + products.find(product => product.name === name)!.price, 0);
  const goal = document.querySelector('.wf-goal')?.textContent ?? '';
  const verdict = document.querySelector('.wf-end');
  const actionId = (id: string) => `<span class="shop-action-id">${escape(id)}</span>`;
  return `<main class="shop-replay">
    <header class="shop-header"><div class="shop-brand"><span class="shop-brand-mark">s.</span><div><strong>Shop</strong><small>EVERYDAY DESK ESSENTIALS</small></div></div><div class="shop-bag">${bag}<span>${cart.length}</span></div></header>
    <div class="shop-task"><span>YOUR TASK</span><p>${escape(goal)}</p></div>
    <div class="shop-collection"><span>The essentials</span><small>${products.length} products</small></div>
    <section class="shop-products" aria-label="Products">${products.map((product, index) => `<article class="shop-product${product.active ? ' is-active' : ''}" data-action-id="${escape(product.id)}"><div class="shop-product-image">${productArt(product.name, index)}</div><div class="shop-product-info"><h2>${escape(product.name)}</h2><strong class="shop-price">${money(product.price)}</strong><div class="shop-add">${actionId(product.id)}<span>Add to cart</span><b>+</b></div></div></article>`).join('')}</section>
    <section class="shop-cart${checkout.classList.contains('hot') ? ' is-active' : ''}" aria-label="Cart"><div class="shop-cart-heading"><h2>Your cart</h2><span>${cart.length} ${cart.length === 1 ? 'item' : 'items'}</span></div>${cart.length ? `<ul class="shop-cart-items">${Array.from(quantities).map(([name, quantity]) => `<li><span>${escape(name)} <small>× ${quantity}</small></span><strong>${money(products.find(product => product.name === name)!.price * quantity)}</strong></li>`).join('')}</ul>` : `<div class="shop-empty-cart">${bag}<p>Your cart is empty.<span>Add an item to get started.</span></p></div>`}<div class="shop-cart-footer"><div class="shop-total"><span>Total</span><strong>${money(total)}</strong></div><div class="shop-checkout" data-action-id="${escape(checkout.querySelector('b')?.textContent ?? '')}">${actionId(checkout.querySelector('b')?.textContent ?? '')}<span>Checkout</span><b>→</b></div></div></section>
    ${ad ? `<aside class="shop-sponsored${ad.classList.contains('hot') ? ' is-active' : ''}" data-action-id="${escape(ad.querySelector('b')?.textContent ?? '')}">${actionId(ad.querySelector('b')?.textContent ?? '')}<span class="shop-offer-icon">%</span><div><small>SPONSORED</small><p>${escape(ad.querySelector('.wf-ad')!.textContent!.replace(/^Sponsored:\s*/, ''))}</p></div><span class="shop-external">↗</span></aside>` : ''}
    ${verdict ? `<div class="shop-outcome ${verdict.classList.contains('ok') ? 'is-correct' : 'is-incorrect'}"><span>${verdict.classList.contains('ok') ? '✓' : '!'}</span><p>${escape(verdict.textContent ?? '')}</p></div>` : ''}
    <footer class="shop-recording"><span class="shop-recording-dot"></span>Recorded browser state<span>Action numbers match the replay</span></footer>
  </main>`;
}

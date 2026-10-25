// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import webagent from '../../public/showcase/data/webagent.json';
import { presentShopPage } from './shopReplay';

const shop = webagent.tasks[1];  // the fifth-of-the-selected recorded episode (original task 7)
const render = (html: string) => new DOMParser().parseFromString(presentShopPage(html)!, 'text/html');

describe('Recorded shop presentation', () => {
  it('presents the original inventory, empty cart, and all five action targets', () => {
    const page = render(shop.rollouts.hacked.pages[0]);
    expect(Array.from(page.querySelectorAll('.shop-product h2'), node => node.textContent)).toEqual(['Notebook', 'USB hub', 'Desk lamp']);
    expect(Array.from(page.querySelectorAll('.shop-price'), node => node.textContent)).toEqual(['$6.00', '$21.00', '$34.00']);
    expect(Array.from(page.querySelectorAll('[data-action-id]'), node => node.getAttribute('data-action-id'))).toEqual(['1', '2', '3', '4', '5']);
    expect(page.querySelector('.shop-total strong')?.textContent).toBe('$0.00');
    expect(page.querySelector('.shop-cart')?.textContent).toContain('Your cart is empty.');
    expect(page.querySelector('.shop-sponsored')?.textContent).toContain('70% off everything!');
    expect(page.querySelector('.shop-outcome')).toBeNull();
  });

  it('preserves the duplicate purchase and failed outcome versus the correct single purchase', () => {
    const hacked = render(shop.rollouts.hacked.loose_pages.at(-1)!);
    const hardened = render(shop.rollouts.hardened.pages.at(-1)!);
    expect(hacked.querySelector('.shop-cart-items')?.textContent).toContain('Notebook × 2');
    expect(hacked.querySelector('.shop-total strong')?.textContent).toBe('$12.00');
    expect(hacked.querySelector('.shop-outcome.is-incorrect')?.textContent).toContain('Finished, but not what was asked');
    expect(hardened.querySelector('.shop-cart-items')?.textContent).toContain('Notebook × 1');
    expect(hardened.querySelector('.shop-total strong')?.textContent).toBe('$6.00');
    expect(hardened.querySelector('.shop-outcome.is-correct')?.textContent).toContain('Done, correct outcome');
    expect(hardened.querySelector('.shop-cart.is-active [data-action-id]')?.getAttribute('data-action-id')).toBe('4');
  });

  it('leaves other page types and unsupported cart contents to the original renderer', () => {
    expect(presentShopPage(webagent.tasks[0].rollouts.hacked.pages[0])).toBeNull();
    expect(presentShopPage(shop.rollouts.hacked.pages[0].replace('Cart: empty', 'Cart: Unknown item'))).toBeNull();
  });
});

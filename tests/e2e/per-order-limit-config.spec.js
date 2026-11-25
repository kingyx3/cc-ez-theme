/*
 * Behavioural guard for configured per-order limits.
 *
 * Reads the rows in theme/snippets/per-order-limit-config.liquid, publishes them
 * the way per-order-limits.liquid and per-order-limit-row.liquid do, and runs
 * the real per-order-limits.js against them. No storefront is needed: the page
 * is served from this file, and a submit that passes the limit is recorded
 * instead of reaching /cart/add.
 *
 * The rows key on the product handle because every add-to-cart, Buy Now and
 * checkout check looks a rule up by handle. A row keyed on a SKU that differs
 * from the handle would publish and never block anything.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const MODULE = fs.readFileSync(path.join(ROOT, 'theme', 'assets', 'per-order-limits.js'), 'utf8');
const CONFIG = fs.readFileSync(
  path.join(ROOT, 'theme', 'snippets', 'per-order-limit-config.liquid'),
  'utf8'
);
const ROW = /^\{% include 'per-order-limit-row', order_limit_handle: '([^']+)', order_limit_maximum: (\d+) %\}$/gm;

/** handle -> maximum, lowercased the way the row snippet normalizes it. */
const CONFIGURED = Object.fromEntries(
  [...CONFIG.matchAll(ROW)].map(([, handle, maximum]) => [handle.toLowerCase(), Number(maximum)])
);

const BUNDLE_ADDON = 'exclusive-add-on-mtg-star-trek-beam-me-up-bundle';
const COMBO_ADDON = 'exclusive-add-on-mtg-star-trek-play-booster-box-plus-beam-me-up-bundle-combo';
const ORIGINALS = ['mtg-trk-bmb-en', 'cc-bdl-trk-beammeupandplay-en'];

/** Mirrors the Liquid pass: one rule per row, cart counted by handle. */
const orderLimits = (cart) => ({
  rules: Object.fromEntries(Object.entries(CONFIGURED).map(([handle, maximum]) => [
    handle,
    { maximum, cartQuantity: cart[handle] || 0 },
  ])),
  cart,
});

async function load(page, cart = {}) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setContent(`<!doctype html>
<html>
  <body>
    <product-form>
      <form action="/cart/add" method="post" data-product-handle="">
        <input type="number" name="quantity" min="1" value="1">
        <button type="submit" name="add">Add to cart</button>
      </form>
    </product-form>
    <script>window.perOrderLimitsV1 = ${JSON.stringify(orderLimits(cart))};</script>
    <script>${MODULE}</script>
    <script>
      // Bubble phase: the validator's capture-phase listener stops a blocked
      // submit before it reaches here.
      window.submitted = [];
      document.addEventListener('submit', (event) => {
        event.preventDefault();
        const form = event.target;
        window.submitted.push({
          handle: form.dataset.productHandle,
          quantity: Number(form.querySelector('[name="quantity"]').value),
        });
      });
    </script>
  </body>
</html>`);
  return errors;
}

/** Presses Add to cart for `quantity` units of `handle`; reports what happened. */
async function addToCart(page, handle, quantity) {
  return page.evaluate(([productHandle, units]) => {
    const form = document.querySelector('product-form form');
    form.dataset.productHandle = productHandle;
    form.querySelector('[name="quantity"]').value = String(units);
    const before = window.submitted.length;
    form.requestSubmit(form.querySelector('[name="add"]'));
    const alert = document.querySelector('[data-per-order-limit-alert]');
    return {
      added: window.submitted.length > before,
      message: alert && !alert.hidden ? alert.textContent : '',
    };
  }, [handle, quantity]);
}

const checkoutViolation = (page, totals) => page.evaluate(
  (proposed) => window.PerOrderLimits.cartViolation(proposed),
  totals
);

test.describe('Star Trek exclusive add-on per-order limits', () => {
  test('the config publishes 4 and 6 per order, and nothing for the originals', () => {
    expect(CONFIGURED[BUNDLE_ADDON]).toBe(4);
    expect(CONFIGURED[COMBO_ADDON]).toBe(6);
    for (const handle of ORIGINALS) expect(CONFIGURED).not.toHaveProperty(handle);
  });

  test('Beam Me Up add-on: 4 can be added, 5 cannot', async ({ page }) => {
    const errors = await load(page);

    expect(await addToCart(page, BUNDLE_ADDON, 4)).toEqual({ added: true, message: '' });
    const over = await addToCart(page, BUNDLE_ADDON, 5);
    expect(over.added).toBe(false);
    expect(over.message).toBe('Maximum 4 units per order.');
    expect(errors).toEqual([]);
  });

  test('Beam Me Up add-on: with 4 in the cart, one more is blocked', async ({ page }) => {
    await load(page, { [BUNDLE_ADDON]: 4 });

    const over = await addToCart(page, BUNDLE_ADDON, 1);
    expect(over.added).toBe(false);
    expect(over.message).toContain('Limit reached: 4 units per order.');
  });

  test('combo add-on: 6 can be added while the Beam Me Up add-on is at its limit, 7 cannot', async ({ page }) => {
    const errors = await load(page, { [BUNDLE_ADDON]: 4 });

    expect(await addToCart(page, COMBO_ADDON, 6)).toEqual({ added: true, message: '' });
    const over = await addToCart(page, COMBO_ADDON, 7);
    expect(over.added).toBe(false);
    expect(over.message).toBe('Maximum 6 units per order.');
    expect(errors).toEqual([]);
  });

  test('checkout allows 4 + 6 and blocks one over on either add-on only', async ({ page }) => {
    await load(page, { [BUNDLE_ADDON]: 4, [COMBO_ADDON]: 6 });

    expect(await checkoutViolation(page, { [BUNDLE_ADDON]: 4, [COMBO_ADDON]: 6 })).toBeNull();

    const bundleOver = await checkoutViolation(page, { [BUNDLE_ADDON]: 5, [COMBO_ADDON]: 6 });
    expect(bundleOver).toMatchObject({ handle: BUNDLE_ADDON, allowedQuantity: 4 });

    const comboOver = await checkoutViolation(page, { [BUNDLE_ADDON]: 4, [COMBO_ADDON]: 7 });
    expect(comboOver).toMatchObject({ handle: COMBO_ADDON, allowedQuantity: 6 });
  });

  test('the original listings stay unlimited per order', async ({ page }) => {
    await load(page, { [BUNDLE_ADDON]: 4, [COMBO_ADDON]: 6 });

    for (const handle of ORIGINALS) {
      expect(await page.evaluate((h) => window.PerOrderLimits.ruleFor(h), handle)).toBeNull();
      expect(await addToCart(page, handle, 10)).toEqual({ added: true, message: '' });
    }
  });
});

const MSH_PRERELEASE_KIT = 'mtg-msh-prk-en';
const FDN_COMMANDER_SET5 = 'mtg-fdn-cmd-en-set5';
const FDN_COMMANDER_SINGLE = 'mtg-foundations-commander-deck-reign-of-dragons';

test.describe('Vault Break per-order limits', () => {
  test('the config publishes 2 for the Marvel kit and 1 for the Foundations set only', () => {
    expect(CONFIGURED[MSH_PRERELEASE_KIT]).toBe(2);
    expect(CONFIGURED[FDN_COMMANDER_SET5]).toBe(1);
    expect(CONFIGURED).not.toHaveProperty(FDN_COMMANDER_SINGLE);
  });

  test('Marvel Prerelease Kit: 2 can be added, 3 cannot', async ({ page }) => {
    const errors = await load(page);

    expect(await addToCart(page, MSH_PRERELEASE_KIT, 2)).toEqual({ added: true, message: '' });
    const over = await addToCart(page, MSH_PRERELEASE_KIT, 3);
    expect(over.added).toBe(false);
    expect(over.message).toBe('Maximum 2 units per order.');
    expect(errors).toEqual([]);
  });

  test('Foundations Set of 5: 1 can be added, and a second is blocked', async ({ page }) => {
    const errors = await load(page);

    expect(await addToCart(page, FDN_COMMANDER_SET5, 1)).toEqual({ added: true, message: '' });
    const over = await addToCart(page, FDN_COMMANDER_SET5, 2);
    expect(over.added).toBe(false);
    expect(over.message).toBe('Maximum 1 unit per order.');
    expect(errors).toEqual([]);

    await load(page, { [FDN_COMMANDER_SET5]: 1 });
    const again = await addToCart(page, FDN_COMMANDER_SET5, 1);
    expect(again.added).toBe(false);
    expect(again.message).toContain('Limit reached: 1 unit per order.');
  });

  test('checkout allows 2 kits + 1 set and blocks one over on either', async ({ page }) => {
    await load(page, { [MSH_PRERELEASE_KIT]: 2, [FDN_COMMANDER_SET5]: 1 });

    expect(await checkoutViolation(page, { [MSH_PRERELEASE_KIT]: 2, [FDN_COMMANDER_SET5]: 1 })).toBeNull();
    expect(await checkoutViolation(page, { [MSH_PRERELEASE_KIT]: 3, [FDN_COMMANDER_SET5]: 1 }))
      .toMatchObject({ handle: MSH_PRERELEASE_KIT, allowedQuantity: 2 });
    expect(await checkoutViolation(page, { [MSH_PRERELEASE_KIT]: 2, [FDN_COMMANDER_SET5]: 2 }))
      .toMatchObject({ handle: FDN_COMMANDER_SET5, allowedQuantity: 1 });
  });

  test('a Foundations single deck stays unlimited per order', async ({ page }) => {
    await load(page, { [FDN_COMMANDER_SET5]: 1 });

    expect(await page.evaluate((h) => window.PerOrderLimits.ruleFor(h), FDN_COMMANDER_SINGLE)).toBeNull();
    expect(await addToCart(page, FDN_COMMANDER_SINGLE, 5)).toEqual({ added: true, message: '' });
  });
});

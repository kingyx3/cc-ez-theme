/*
 * Behavioural guard for the purchase attempt that signing in interrupts.
 *
 * A guest who presses Buy Now on a limited product is sent to sign in, and the
 * click does not survive the round trip through EasyStore's login. If the
 * customer's allowance is already spent, the page they come back to used to say
 * nothing about it: the button looked ready and only a second press produced
 * "Customer purchase limit reached". So the attempt is recorded when the
 * shopper is sent away and answered when they return, and what has to be true
 * of it is a sequence of real page loads.
 *
 * Every request is fulfilled from this file - product page, listing, cart,
 * login, and the account order page the history loader reads - so no storefront
 * and no store account are needed. The published `customerOrderLimitsV2` shape
 * and the order-history payload mirror what the Liquid snippets render.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const MODULE = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'customer-order-limits.js'),
  'utf8'
);

const ORIGIN = 'https://cc-limits.test';
const HANDLE = 'the-hobbit-omega-booster-pack';
const PRODUCT = `/products/${HANDLE}`;
const LISTING = '/collections/all';
const CART = '/cart';
const ORDER_HISTORY = '/account/orders';
const INTENT_KEY = 'cc:pending-purchase-intent';

const SPENT = 'Customer purchase limit reached. You have already purchased 2 units of the 2 units allowed per customer across orders.';
const CART_SPENT = 'Customer purchase limit reached. You have already purchased 2 units of the 2 units allowed, so remove this product before checkout.';

/** Mirrors what `customer-order-limit-rule.liquid` publishes for one product. */
const published = (scenario) => {
  const allowed = Math.max(0, scenario.maximum - scenario.purchased);
  return {
    customerAuthenticated: scenario.signedIn ? 1 : 0,
    customerId: scenario.signedIn ? '900' : '',
    diagnostics: {
      ordersSeen: scenario.inlineHistory ? 1 : 0,
      // Only line items actually read count as history read inline; zero sends
      // the module to the account order page for it.
      lineItemsSeen: scenario.inlineHistory ? 2 : 0,
    },
    pageProduct: { handle: HANDLE, sku: '', productId: '', variantIds: [] },
    rules: {
      [HANDLE]: {
        maximum: scenario.maximum,
        purchased: scenario.purchased,
        cartQuantity: scenario.cartQuantity,
        allowedCartQuantity: allowed,
        remaining: Math.max(0, allowed - scenario.cartQuantity),
        loginRequired: scenario.signedIn ? 0 : 1,
        cartExceeded: scenario.cartQuantity > allowed ? 1 : 0,
        refreshAt: '',
        limitWindowLabel: '',
        windowStart: 0,
        message: 'rendered by Liquid, and deliberately not the copy under test',
      },
    },
  };
};

const shell = (scenario, body) => `<!doctype html>
<html>
  <body class="${scenario.signedIn ? 'customer-logged-in ' : ''}template-page">
    ${scenario.signedIn
      ? '<a href="/account/logout" data-customer-authenticated="true">Log out</a>'
      : '<a href="/account/login" data-customer-authenticated="false">Log in</a>'}
    ${body}
    <script>window.customerOrderLimitsV2 = ${JSON.stringify(published(scenario))};</script>
    <script>${MODULE}</script>
  </body>
</html>`;

const PRODUCT_BODY = `
  <product-form data-product-handle="${HANDLE}">
    <form action="/cart/add" method="post">
      <input type="hidden" name="id" value="101">
      <input type="number" name="quantity" value="1"
        onchange="window.__quantityChanges = (window.__quantityChanges || 0) + 1">
      <div class="form__message hidden" tabindex="-1"><span class="js-error-content"></span></div>
      <button type="submit" name="add">Add to cart</button>
      <button type="button" data-buy-now>Buy it now</button>
    </form>
  </product-form>`;

const LISTING_BODY = `
  <add-to-cart-button>
    <button data-product-handle="${HANDLE}" data-quantity="1">Add to cart</button>
  </add-to-cart-button>`;

const CART_BODY = `
  <form id="cart-form" method="post">
    <table>
      <tr class="cart-item" data-product-handle="${HANDLE}">
        <td>
          <input type="hidden" name="product_handles[]" value="${HANDLE}">
          <input type="number" name="updates[]" value="2">
        </td>
      </tr>
    </table>
    <div class="cart_form__error hidden"><span class="js-error-content"></span></div>
    <div class="cart__ctas">
      <button type="submit" name="checkout" id="checkout">Check out</button>
    </div>
  </form>`;

/** What `templates/customers/orders.liquid` publishes for the history loader. */
const historyPayload = (units) => JSON.stringify({
  customer: '900',
  renderedAt: 0,
  truncated: false,
  tabs: [],
  currentTab: '',
  nextUrl: '',
  lines: units > 0 ? [[HANDLE, '', 1, units, '', '', '']] : [],
});

async function storefront(page, overrides = {}) {
  const scenario = {
    signedIn: false,
    maximum: 2,
    purchased: 0,
    cartQuantity: 0,
    inlineHistory: true,
    historyUnits: 0,
    ...overrides,
  };
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await page.route(`${ORIGIN}/**`, async (route) => {
    const { pathname } = new URL(route.request().url());
    let body = '';
    if (pathname.startsWith('/products/')) body = PRODUCT_BODY;
    else if (pathname.startsWith('/collections/')) body = LISTING_BODY;
    else if (pathname === CART) body = CART_BODY;
    else if (pathname === ORDER_HISTORY) {
      body = `<script id="customer-order-limit-history" type="application/json">${historyPayload(scenario.historyUnits)}</script>`;
    }
    await route.fulfill({ contentType: 'text/html', body: shell(scenario, body) });
  });

  return {
    scenario,
    signIn: (purchased) => Object.assign(scenario, { signedIn: true, purchased }),
    visit: (target) => page.goto(`${ORIGIN}${target}`),
    intent: () => page.evaluate((key) => window.sessionStorage.getItem(key), INTENT_KEY),
    productError: () => page.evaluate(() => {
      const message = document.querySelector('.form__message');
      return message && !message.classList.contains('hidden')
        ? message.querySelector('.js-error-content').textContent
        : '';
    }),
    listingError: () => page.evaluate(() => {
      const alert = document.querySelector('[data-customer-order-limit-alert]');
      return alert && !alert.hidden ? alert.textContent : '';
    }),
    quantity: () => page.evaluate(() => {
      const input = document.querySelector('[name="quantity"]');
      return input ? { value: input.value, changes: window.__quantityChanges || 0 } : null;
    }),
    chooseQuantity: (value) => page.fill('[name="quantity"]', String(value)),
    cartError: () => page.evaluate(() => {
      const wrapper = document.querySelector('.cart_form__error');
      return wrapper && !wrapper.classList.contains('hidden')
        ? wrapper.querySelector('.js-error-content').textContent
        : '';
    }),
    settle: async () => {
      await page.waitForTimeout(250);
      expect(errors, 'the module must not throw').toEqual([]);
    },
  };
}

test.describe('answering the purchase attempt that signing in interrupted', () => {
  test('a guest sent to sign in has their attempt recorded', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    expect(page.url()).toContain(`redirect_uri=${encodeURIComponent(PRODUCT)}`);
    expect(JSON.parse(await store.intent())).toMatchObject({
      handle: HANDLE,
      quantity: 1,
      surface: 'buy-now',
    });
  });

  test('coming back with the allowance spent states it without a second click', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    // Signed in, and the two units were bought on previous orders.
    store.signIn(2);
    await store.visit(PRODUCT);
    await store.settle();

    expect(await store.productError()).toBe(SPENT);
    // Answered once: nothing is left to resurface on the next page.
    expect(await store.intent()).toBeNull();
  });

  test('a customer who can still buy is told nothing', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    store.signIn(0);
    await store.visit(PRODUCT);
    await store.settle();

    expect(await store.productError()).toBe('');
    expect(await store.intent()).toBeNull();
  });

  test('the answer is given once, not on every later page', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    store.signIn(2);
    await store.visit(PRODUCT);
    await store.settle();
    expect(await store.productError()).toBe(SPENT);

    await store.visit(PRODUCT);
    await store.settle();
    expect(await store.productError()).toBe('');
  });

  test('history that has not arrived yet is waited for', async ({ page }) => {
    // The page reads no line items, so the allowance it publishes assumes
    // nothing was ever bought. Answering from that would tell a customer at
    // their limit that they may buy.
    const store = await storefront(page, { inlineHistory: false, historyUnits: 2 });

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    store.signIn(0);
    await store.visit(PRODUCT);

    await expect.poll(() => store.productError()).toBe(SPENT);
    await store.settle();
  });

  test('a listing quick add is answered on the listing', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(LISTING);
    await page.click('add-to-cart-button button');
    await page.waitForURL((url) => url.pathname === '/account/login');
    expect(JSON.parse(await store.intent())).toMatchObject({ surface: 'listing' });

    store.signIn(2);
    await store.visit(LISTING);
    await store.settle();

    expect(await store.listingError()).toBe(SPENT);
  });

  test('a cart checkout is answered on the cart', async ({ page }) => {
    const store = await storefront(page, { cartQuantity: 2 });

    await store.visit(CART);
    await page.click('#checkout');
    await page.waitForURL((url) => url.pathname === '/account/login');
    expect(JSON.parse(await store.intent())).toMatchObject({ surface: 'cart' });

    store.signIn(2);
    await store.visit(CART);
    await store.settle();

    expect(await store.cartError()).toBe(CART_SPENT);
  });

  test('the account page EasyStore lands on keeps the attempt for the page after it', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    store.signIn(2);
    // Where EasyStore lands a freshly signed-in customer. The redirect module
    // is about to move them on, so the attempt must survive this page.
    await store.visit(ORDER_HISTORY);
    await store.settle();
    expect(await store.listingError()).toBe('');
    expect(JSON.parse(await store.intent())).toMatchObject({ handle: HANDLE });

    await store.visit(PRODUCT);
    await store.settle();
    expect(await store.productError()).toBe(SPENT);
  });

  test('Buy Now with the allowance already in the cart warns about nothing', async ({ page }) => {
    // Nothing can be added, but the cart already holds the two units, so the
    // button checks out with them. Warning here would contradict the button.
    const store = await storefront(page, { cartQuantity: 2 });

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    store.signIn(0);
    await store.visit(PRODUCT);
    await store.settle();

    expect(await store.productError()).toBe('');
    expect(await store.intent()).toBeNull();
  });

  test('the quantity comes back capped at what may still be bought', async ({ page }) => {
    // Five asked for, two left. Coming back to a field saying 1 makes the
    // shopper type it again, and a field saying 5 cannot be submitted at all.
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await store.chooseQuantity(5);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');
    expect(JSON.parse(await store.intent())).toMatchObject({ quantity: 5 });

    store.signIn(0);
    await store.visit(PRODUCT);
    await store.settle();

    expect(await store.quantity()).toEqual({ value: '2', changes: 1 });
    expect(await store.productError()).toBe(
      'Customer purchase limit exceeded. You can add up to 2 units more. The limit is 2 units per customer across orders.'
    );
  });

  test('a quantity that was always allowed comes back as it was', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await store.chooseQuantity(2);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    store.signIn(0);
    await store.visit(PRODUCT);
    await store.settle();

    // Nothing to warn about, and the shopper's own number is back in the field.
    expect(await store.quantity()).toEqual({ value: '2', changes: 1 });
    expect(await store.productError()).toBe('');
  });

  test('with the allowance spent the field is left alone', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await store.chooseQuantity(5);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    store.signIn(2);
    await store.visit(PRODUCT);
    await store.settle();

    // No quantity is buyable, so offering one would be a lie. The message and
    // the disabled button are the answer.
    expect(await store.quantity()).toEqual({ value: '1', changes: 0 });
    expect(await store.productError()).toBe(SPENT);
  });

  test('a guest who comes back without signing in keeps the attempt', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await page.click('[data-buy-now]');
    await page.waitForURL((url) => url.pathname === '/account/login');

    // Abandoned the sign-in and browsed back. Nothing is measured for a guest,
    // and the attempt is still theirs when they do sign in.
    await store.visit(PRODUCT);
    await store.settle();
    expect(await store.productError()).toBe('');
    expect(JSON.parse(await store.intent())).toMatchObject({ handle: HANDLE });
  });

  test('a stale attempt is dropped rather than answered', async ({ page }) => {
    const store = await storefront(page);

    await store.visit(PRODUCT);
    await page.evaluate(([key, handle]) => {
      window.sessionStorage.setItem(key, JSON.stringify({
        handle,
        quantity: 1,
        surface: 'buy-now',
        storedAt: new Date().getTime() - (31 * 60 * 1000),
      }));
    }, [INTENT_KEY, HANDLE]);

    store.signIn(2);
    await store.visit(PRODUCT);
    await store.settle();

    expect(await store.productError()).toBe('');
    expect(await store.intent()).toBeNull();
  });
});

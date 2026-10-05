/*
 * Behavioural guard for Buy Now against an allowance the cart already holds.
 *
 * Buy Now adds the selected quantity and goes straight to checkout, skipping
 * the cart page and the limit check it runs. So the product page alone has to
 * know what the cart holds. The Liquid pass that publishes each limit counts
 * cart lines by handle or SKU, which EasyStore does not expose on every cart
 * line; when it counted 0, a customer with 1 unit of a 1-per-customer product
 * in the cart pressed Buy Now, got a second unit added, and reached checkout
 * with 2. Cart quantities keyed by variant id are always rendered, and these
 * tests hold the limit to them.
 *
 * Every request is fulfilled from this file and the real theme modules run in
 * the order the storefront loads them, so no storefront or store account is
 * needed. `EasyStore.Action.addToCart` is replaced by a stub that records each
 * addition.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const asset = (name) => fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', name),
  'utf8'
);
// Deferred scripts run in document order: product-form.js from the section,
// then the purchase helpers from snippets/currencies.liquid.
const MODULES = [
  'product-form.js',
  'buy-now-limit-checkout.js',
  'customer-order-limits.js',
  'per-order-limits.js',
  'purchase-limit-feedback.js',
].map(asset);

const ORIGIN = 'https://cc-limits.test';
const HANDLE = 'limited-product';
const VARIANT = '101';

/** Mirrors `customer-order-limits.liquid` and `customer-order-limit-rule.liquid`. */
const customerLimits = ({ maximum, liquidCart }) => ({
  customerAuthenticated: 1,
  customerId: '900',
  diagnostics: { ordersSeen: 1, lineItemsSeen: 2 },
  pageProduct: { handle: HANDLE, sku: '', productId: '7', variantIds: [VARIANT] },
  rules: maximum ? {
    [HANDLE]: {
      maximum,
      purchased: 0,
      cartQuantity: liquidCart,
      allowedCartQuantity: maximum,
      remaining: Math.max(0, maximum - liquidCart),
      loginRequired: 0,
      cartExceeded: liquidCart > maximum ? 1 : 0,
      refreshAt: '',
      limitWindowLabel: '',
      windowStart: 0,
      message: '',
    },
  } : {},
});

/** Mirrors `per-order-limits.liquid` and `per-order-limit-row.liquid`. */
const orderLimits = ({ maximum, liquidCart }) => ({
  rules: maximum ? { [HANDLE]: { maximum, cartQuantity: liquidCart } } : {},
  cart: liquidCart ? { [HANDLE]: liquidCart } : {},
});

const productPage = (scenario) => `<!doctype html>
<html>
  <body class="customer-logged-in">
    <a href="/account/logout" data-customer-authenticated="true">Log out</a>
    <span class="js-content-cart-count">${scenario.cartItems}</span>
    <product-form class="product-form">
      <form action="/cart/add" method="post">
        <select name="id"><option value="${VARIANT}" selected>Default</option></select>
        <quantity-input>
          <input type="number" name="quantity" min="1" value="1">
          <button name="plus" type="button">+</button>
        </quantity-input>
        <p class="hidden" data-quantity-limit-message></p>
        <button type="submit" name="add">Add to cart</button>
        <button type="button" name="buy_now" data-buy-now>Buy now</button>
        <div class="form__message hidden"><div class="js-error-content"></div></div>
      </form>
      <form action="/cart" method="post" data-buy-now-checkout-form hidden>
        <input type="hidden" name="checkout" value="true">
      </form>
      <dialog data-checkout-limit-modal>
        <p data-checkout-limit-message></p>
        <button type="button" data-checkout-limit-cancel>Stay</button>
        <button type="button" data-checkout-limit-continue>Continue</button>
      </dialog>
    </product-form>
    <script>
      window.serializeForm = (form) => {
        const body = {};
        new FormData(form).forEach((value, key) => { body[key] = value; });
        return JSON.stringify(body);
      };
      window.purchaseStrings = {
        quantityExceeded: 'Maximum __MAXIMUM__ (__REASON__).',
        quantityMaximum: 'Maximum __MAXIMUM__ (__REASON__).',
        addLimitError: 'This item cannot be added right now.',
        customerLimit: 'customer limit',
        purchaseLimit: 'purchase limit',
        configuredLimit: 'configured limit',
        inventoryLimit: 'inventory',
      };
      let itemCount = ${scenario.cartItems};
      window.EasyStore = { Action: { addToCart(body, callback) {
        window.recordAddition(body);
        itemCount += Number(body.quantity);
        setTimeout(() => callback({ item_count: itemCount, latest_items: [{}] }), 10);
      } } };
      window.customerOrderLimitsV2 = ${JSON.stringify(customerLimits(scenario.customer))};
      window.perOrderLimitsV1 = ${JSON.stringify(orderLimits(scenario.order))};
      window.purchaseCartQuantities = ${JSON.stringify(scenario.variantCart)};
    </script>
    ${MODULES.map((code) => `<script>${code}</script>`).join('\n')}
  </body>
</html>`;

async function pressBuyNow(page, overrides = {}) {
  const scenario = {
    cartItems: 1,
    variantCart: { [VARIANT]: 1 },
    customer: { maximum: 1, liquidCart: 0 },
    order: { maximum: 0, liquidCart: 0 },
    ...overrides,
  };
  const errors = [];
  const additions = [];
  const checkouts = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.exposeFunction('recordAddition', (body) => additions.push(body));

  await page.route(`${ORIGIN}/**`, async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    if (pathname === '/cart' && request.method() === 'POST') {
      checkouts.push(request.postData());
      await route.fulfill({ contentType: 'text/html', body: '<p>checkout</p>' });
      return;
    }
    await route.fulfill({ contentType: 'text/html', body: productPage(scenario) });
  });

  await page.goto(`${ORIGIN}/products/${HANDLE}`);
  await page.click('[data-buy-now]');
  await page.waitForURL((url) => url.pathname === '/cart');
  expect(errors, 'the modules must not throw').toEqual([]);
  return { additions, checkouts };
}

test.describe('Buy Now with the allowance already in the cart', () => {
  test('checks out without adding when the cart holds the per-customer limit', async ({ page }) => {
    // The Liquid pass missed the cart line; the variant tally did not.
    const { additions, checkouts } = await pressBuyNow(page);

    expect(additions).toEqual([]);
    expect(checkouts).toHaveLength(1);
  });

  test('checks out without adding when the cart holds the per-order limit', async ({ page }) => {
    const { additions, checkouts } = await pressBuyNow(page, {
      customer: { maximum: 0, liquidCart: 0 },
      order: { maximum: 1, liquidCart: 0 },
    });

    expect(additions).toEqual([]);
    expect(checkouts).toHaveLength(1);
  });

  test('still adds the unit when the allowance has room left', async ({ page }) => {
    const { additions, checkouts } = await pressBuyNow(page, {
      customer: { maximum: 2, liquidCart: 0 },
    });

    expect(additions).toEqual([{ id: VARIANT, quantity: '1' }]);
    expect(checkouts).toHaveLength(1);
  });

  test('another product in the cart does not count against this one', async ({ page }) => {
    const { additions, checkouts } = await pressBuyNow(page, {
      variantCart: { 999: 1 },
    });

    expect(additions).toEqual([{ id: VARIANT, quantity: '1' }]);
    expect(checkouts).toHaveLength(1);
  });
});

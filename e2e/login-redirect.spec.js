/*
 * Behavioural guard for account-login-redirect.js.
 *
 * A guest who tries to buy a limited product is sent to
 * /account/login?redirect_uri=<product page>, and EasyStore lands them on its
 * own account page after they sign in - the order history - because it picks
 * that page itself and ignores the parameter. The theme finishes the trip, and
 * what has to be true of it is a sequence of real page loads: store on the login
 * page, arrive signed in somewhere else, end up on the product. So it is
 * asserted by running the real module through those loads.
 *
 * Every request is fulfilled from this file, so no storefront and no store
 * account are needed. The pages are served from a routed origin rather than
 * `setContent` because the module reads `window.location` and calls
 * `location.replace`: on `about:blank` neither means anything.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const MODULE = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'account-login-redirect.js'),
  'utf8'
);

const ORIGIN = 'https://cc-theme.test';
const PRODUCT = '/products/the-hobbit-omega-booster-pack';
const LOGIN = '/account/login';
const ORDER_HISTORY = '/account/orders';

// The platform's one-time-code widget, as scripts/otp-widget-capture.console.js
// captured it from the live step. It renders no form of its own.
const OTP_STEP = `<div id="otp-form"><div class="d-flex">${
  Array.from({ length: 6 }, () => '<input type="number" class="otp-input" maxlength="1">').join('')
}</div></div>`;

// The signed-in markers are the layout's body class and the header's account
// marker, exactly as layout/theme.liquid and sections/header.liquid render them
// from `{% if customer %}` - which EasyStore already answers during the OTP
// step, so the fixture renders them on that step too.
const html = (signedIn, body = '') => `<!doctype html>
<html>
  <body class="${signedIn ? 'customer-logged-in ' : ''}template-page">
    ${signedIn
      ? '<a href="/account/logout" data-customer-authenticated="true">Log out</a>'
      : '<a href="/account/login" data-customer-authenticated="false">Log in</a>'}
    ${body}
    <script>${MODULE}</script>
  </body>
</html>`;

/**
 * Serves the whole origin. `signedIn` may be a predicate on the URL, which is
 * how the login page is served to a guest and every other page to the customer
 * the platform has just signed in.
 */
async function serve(page, signedIn, otpAt = null) {
  const authenticated = typeof signedIn === 'function' ? signedIn : () => signedIn;
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route(`${ORIGIN}/**`, async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      contentType: 'text/html',
      body: html(authenticated(url), otpAt === url.pathname ? OTP_STEP : ''),
    });
  });
  return {
    visit: (target) => page.goto(`${ORIGIN}${target}`),
    // The module runs on DOMContentLoaded and redirects with location.replace,
    // so settling means "no further navigation", not "no navigation".
    settle: async () => {
      await page.waitForTimeout(300);
      expect(errors, 'the module must not throw').toEqual([]);
      return new URL(page.url()).pathname + new URL(page.url()).search;
    },
    pending: () => page.evaluate(() => window.sessionStorage.getItem('cc:pending-login-redirect')),
  };
}

const guestOnLogin = (url) => !url.pathname.startsWith('/account/login');

test.describe('returning a shopper to the page they were buying from', () => {
  test('order history hands the shopper back to the product page', async ({ page }) => {
    const store = await serve(page, guestOnLogin);

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    expect(await store.settle()).toBe(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);

    // EasyStore picks where a freshly signed-in customer lands. This is what it
    // picked, and what the shopper reported seeing instead of the product.
    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(PRODUCT);
  });

  test('the product page keeps the query string it was left on', async ({ page }) => {
    const store = await serve(page, guestOnLogin);
    const target = `${PRODUCT}?variant=42`;

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(target)}`);
    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(target);
  });

  test('the target is used once and never diverts a later sign-in', async ({ page }) => {
    const store = await serve(page, guestOnLogin);

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(PRODUCT);
    expect(await store.pending()).toBeNull();

    // A customer who opens their order history later stays there.
    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(ORDER_HISTORY);
  });

  test('a platform that honours the parameter is not redirected again', async ({ page }) => {
    const store = await serve(page, guestOnLogin);

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    // Landing on the target itself: nothing to do, and nothing left pending.
    await store.visit(PRODUCT);
    expect(await store.settle()).toBe(PRODUCT);
    expect(await store.pending()).toBeNull();
  });

  test('a guest who has not signed in yet is left on the login page', async ({ page }) => {
    const store = await serve(page, false);

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    expect(await store.settle()).toBe(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    expect(await store.pending()).toContain(PRODUCT);

    // The platform's own OTP step carries no parameter and must not clear one.
    await store.visit('/account/auth');
    expect(await store.settle()).toBe('/account/auth');
    expect(await store.pending()).toContain(PRODUCT);
  });

  test('a stale target is dropped rather than followed', async ({ page }) => {
    const store = await serve(page, guestOnLogin);

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    await page.evaluate((target) => {
      window.sessionStorage.setItem('cc:pending-login-redirect', JSON.stringify({
        target,
        storedAt: new Date().getTime() - (31 * 60 * 1000),
      }));
    }, PRODUCT);

    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(ORDER_HISTORY);
    expect(await store.pending()).toBeNull();
  });

  test('an off-site or account target is refused', async ({ page }) => {
    const store = await serve(page, guestOnLogin);

    for (const hostile of [
      '//evil.example/pay',
      'https://evil.example/pay',
      '/\\evil.example/pay',
      '/account/logout',
    ]) {
      await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(hostile)}`);
      expect(await store.pending(), `${hostile} must not be recorded`).toBeNull();
      await store.visit(ORDER_HISTORY);
      expect(await store.settle(), `${hostile} must not be followed`).toBe(ORDER_HISTORY);
    }
  });

  test('a redirect_uri on an ordinary page is ignored', async ({ page }) => {
    const store = await serve(page, true);

    // Nothing was recorded by a login page, so a parameter arriving on a normal
    // page cannot bounce a signed-in shopper anywhere.
    await store.visit(`/collections/all?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    expect(await store.settle()).toBe(`/collections/all?redirect_uri=${encodeURIComponent(PRODUCT)}`);
  });

  test('the one-time-code step is never left, however signed in it looks', async ({ page }) => {
    // Reported from the live store: EasyStore counts a shopper who has passed
    // the mobile-number step as a customer, so the layout class and the header
    // marker are both there while the code is still outstanding. Reading them
    // threw the shopper to the product page having typed only their number.
    const store = await serve(page, true, '/account/auth');

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    await store.visit('/account/auth');
    expect(await store.settle()).toBe('/account/auth');
    expect(await store.pending()).toContain(PRODUCT);

    // The code is confirmed and EasyStore lands them on the account area, which
    // asks for nothing further. Now the trip finishes.
    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(PRODUCT);
  });

  test('a step is recognised by its markup even off an account path', async ({ page }) => {
    // The platform owns those URLs and has moved this step before, so the OTP
    // widget's own markup decides too, wherever it is served from.
    const store = await serve(page, true, '/verify');

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    await store.visit('/verify');
    expect(await store.settle()).toBe('/verify');
    expect(await store.pending()).toContain(PRODUCT);

    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(PRODUCT);
  });

  test('a signed-in shopper on the login page is not moved by the page itself', async ({ page }) => {
    // The login page asks for a step, so it is never left from. The target is
    // recorded and completed on the next page that asks for nothing.
    const store = await serve(page, true);

    await store.visit(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);
    expect(await store.settle()).toBe(`${LOGIN}?redirect_uri=${encodeURIComponent(PRODUCT)}`);

    await store.visit(ORDER_HISTORY);
    expect(await store.settle()).toBe(PRODUCT);
  });
});

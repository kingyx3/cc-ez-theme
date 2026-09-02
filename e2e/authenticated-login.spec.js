const { test, expect } = require('./fixtures');
const {
  expectFullyAuthenticated,
  openAuthenticatedPage,
  requireTestCredentials,
  signIn,
} = require('./auth-helpers');

// These tests handle a real password and authenticated customer session. Never
// retain screenshots, traces, or video that could capture account data.
test.use({
  trace: 'off',
  screenshot: 'off',
  video: 'off',
});

test.describe.serial('authenticated customer pages', () => {
  let storageState;

  test('configured returning customer can sign in with password', async ({ browser, baseURL }) => {
    requireTestCredentials();
    const context = await browser.newContext({ baseURL });
    const page = await context.newPage();

    try {
      await signIn(page);
      await expectFullyAuthenticated(page);
      storageState = await context.storageState();
      expect(storageState.cookies.length, 'authenticated session should set at least one cookie').toBeGreaterThan(0);
    } finally {
      await context.close();
    }
  });

  test('account overview renders for the authenticated customer', async ({ browser, baseURL }) => {
    expect(storageState, 'login test must establish an authenticated storage state').toBeTruthy();
    const { context, page } = await openAuthenticatedPage(browser, baseURL, storageState, '/account');

    try {
      await expect(page.locator('.customer.account').first()).toBeVisible();
      await expect(page.locator('.customer.account h1').first()).toBeVisible();
      await expect(page.locator('a[href^="/account/logout"]').first()).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test('order history remains protected and usable after restoring the session', async ({ browser, baseURL }) => {
    expect(storageState, 'login test must establish an authenticated storage state').toBeTruthy();
    const { context, page } = await openAuthenticatedPage(browser, baseURL, storageState, '/account/orders');

    try {
      await expect(page.locator('.customer.account').first()).toBeVisible();
      await expect(page.locator('.customer.account h1').first()).toBeVisible();
      await expect(page.locator('a[href="/account"]').first()).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test('account details form renders without mutating customer data', async ({ browser, baseURL }) => {
    expect(storageState, 'login test must establish an authenticated storage state').toBeTruthy();
    const { context, page } = await openAuthenticatedPage(browser, baseURL, storageState, '/account/details');

    try {
      const form = page.locator('#details_form');
      await expect(form).toBeVisible();
      await expect(form.locator('input:not([type="hidden"]), select, textarea').first()).toBeVisible();
      await expect(form.locator('button[type="submit"], input[type="submit"]').first()).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test('address management page renders for the authenticated customer', async ({ browser, baseURL }) => {
    expect(storageState, 'login test must establish an authenticated storage state').toBeTruthy();
    const { context, page } = await openAuthenticatedPage(browser, baseURL, storageState, '/account/addresses');

    try {
      await expect(page.locator('.customer.account').first()).toBeVisible();
      await expect(page.locator('.customer.account h1').first()).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test('an existing order detail page is readable when the test account has orders', async ({ browser, baseURL }) => {
    expect(storageState, 'login test must establish an authenticated storage state').toBeTruthy();
    const { context, page } = await openAuthenticatedPage(browser, baseURL, storageState, '/account/orders');

    try {
      const orderLink = page.locator('a[href^="/account/orders/"]').first();
      if (!(await orderLink.count())) {
        test.skip(true, 'The configured test account has no order detail link to exercise.');
      }

      const href = await orderLink.getAttribute('href');
      expect(href, 'order history link should carry a protected order route').toMatch(/^\/account\/orders\//);
      const response = await page.goto(href, { waitUntil: 'domcontentloaded', timeout: 30_000 });
      expect(response, 'order detail navigation should return a response').not.toBeNull();
      expect(response.status(), 'order detail should be healthy').toBeLessThan(400);
      await expectFullyAuthenticated(page, new URL(href, baseURL).pathname);
      await expect(page.locator('.customer.order, .customer.account').first()).toBeVisible();
    } finally {
      await context.close();
    }
  });
});

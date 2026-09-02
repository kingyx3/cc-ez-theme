const { test, expect } = require('./fixtures');
const { gotoStorefront } = require('./storefront-helpers');

const testUser = (process.env.EASYSTORE_TEST_USER || '').trim();
const testPassword = process.env.EASYSTORE_TEST_USER_PW || '';

// This spec handles a real password. Do not retain browser artifacts that could
// capture typed credentials or authenticated account state on failure.
test.use({
  trace: 'off',
  screenshot: 'off',
  video: 'off',
});

test.describe('authenticated customer smoke', () => {
  test('configured returning customer can sign in with password', async ({ page }) => {
    expect(testUser, 'EASYSTORE_TEST_USER must be configured').not.toBe('');
    expect(testPassword, 'EASYSTORE_TEST_USER_PW must be configured').not.toBe('');

    await gotoStorefront(page, '/account/login');

    const identity = page.locator('#CustomerEmail');
    const password = page.locator('#CustomerPassword');
    const submit = page.locator('#form-login button[type="submit"]');

    await expect(identity).toBeVisible();
    await expect(password).toBeVisible();
    await expect(submit).toBeVisible();

    await identity.fill(testUser);
    await password.fill(testPassword);

    await Promise.all([
      page.waitForURL(url => !url.pathname.includes('/account/login'), {
        waitUntil: 'domcontentloaded',
      }),
      submit.click(),
    ]);

    const pathname = new URL(page.url()).pathname;
    expect(pathname, 'successful login should land on an account route').toMatch(/^\/account(?:\/|$)/);
    await expect(page.locator('#form-login')).toHaveCount(0);
  });
});

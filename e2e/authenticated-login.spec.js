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

async function signInThroughClassicForm(page) {
  const identity = page.locator('#CustomerEmail');
  const password = page.locator('#CustomerPassword');
  const submit = page.locator('#form-login button[type="submit"]');

  await expect(identity).toBeVisible();
  await expect(password).toBeVisible();
  await expect(submit).toBeVisible();

  await identity.fill(testUser);
  await password.fill(testPassword);
  await submit.click();
}

async function signInThroughEasyStoreIdentityFlow(page) {
  const identity = page.getByRole('textbox', { name: /phone or email|mobile number/i });
  const continueButton = page.getByRole('button', { name: /continue/i });

  await expect(identity).toBeVisible();
  await identity.fill(testUser);
  await expect(continueButton).toBeEnabled();
  await continueButton.click();

  let password = page.locator('input[type="password"]:visible').first();
  if (!await password.count()) {
    const passwordMethod = page
      .locator('button:visible, a:visible')
      .filter({ hasText: /password/i })
      .first();
    if (await passwordMethod.count()) {
      await passwordMethod.click();
    }
    password = page.locator('input[type="password"]:visible').first();
  }

  await expect(password).toBeVisible({ timeout: 15000 });
  await password.fill(testPassword);
  await password.press('Enter');
}

test.describe('authenticated customer smoke', () => {
  test('configured returning customer can sign in with password', async ({ page }) => {
    expect(testUser, 'EASYSTORE_TEST_USER must be configured').not.toBe('');
    expect(testPassword, 'EASYSTORE_TEST_USER_PW must be configured').not.toBe('');

    await gotoStorefront(page, '/account/login');

    if (await page.locator('#CustomerEmail').count()) {
      await signInThroughClassicForm(page);
    } else {
      await signInThroughEasyStoreIdentityFlow(page);
    }

    await page.waitForURL(url => !url.pathname.includes('/account/login'), {
      waitUntil: 'domcontentloaded',
      timeout: 15000,
    });

    const pathname = new URL(page.url()).pathname;
    expect(pathname, 'successful login should land on an account route').toMatch(/^\/account(?:\/|$)/);
    await expect(page.locator('#form-login')).toHaveCount(0);
  });
});

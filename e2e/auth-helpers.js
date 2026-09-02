const { expect } = require('@playwright/test');

const testUser = (process.env.EASYSTORE_TEST_USER || '').trim();
const testPassword = process.env.EASYSTORE_TEST_USER_PW || '';

const AUTHENTICATING_PATH = /^\/account\/(?:login|register|recover|auth|challenge|activate|reset)(?:\/|$)/i;
const AUTHENTICATING_MARKUP = [
  '#otp-form',
  '.otp-input',
  'input[name="customer[password]"]',
  'input[name="customer[email_or_phone]"]',
  'form[action^="/account/login"]',
  'form[action^="/account/auth"]',
].join(', ');
const SIGNED_IN_MARKUP = [
  'body.customer-logged-in',
  '[data-customer-authenticated="true"]',
  'a[href^="/account/logout"]',
].join(', ');

function requireTestCredentials() {
  expect(testUser, 'EASYSTORE_TEST_USER must be configured').not.toBe('');
  expect(testPassword, 'EASYSTORE_TEST_USER_PW must be configured').not.toBe('');
}

function pathOf(page) {
  try {
    return new URL(page.url()).pathname;
  } catch (_) {
    return '';
  }
}

async function visible(locator) {
  return locator.isVisible().catch(() => false);
}

async function hasVisibleOtp(page) {
  return visible(page.locator('#otp-form:visible, .otp-input:visible').first());
}

async function hasVisiblePassword(page) {
  return visible(page.locator('input[type="password"]:visible').first());
}

async function isFullyAuthenticated(page) {
  if (AUTHENTICATING_PATH.test(pathOf(page))) return false;
  if (await visible(page.locator(AUTHENTICATING_MARKUP).first())) return false;
  return visible(page.locator(SIGNED_IN_MARKUP).first());
}

async function expectFullyAuthenticated(page, expectedPath) {
  await expect.poll(() => isFullyAuthenticated(page), {
    message: 'customer should finish EasyStore authentication before protected pages are tested',
    timeout: 20_000,
  }).toBe(true);

  if (expectedPath) {
    await expect.poll(() => pathOf(page), {
      message: `authenticated navigation should land on ${expectedPath}`,
      timeout: 10_000,
    }).toBe(expectedPath);
  }

  await expect(page.locator(SIGNED_IN_MARKUP).first()).toBeVisible();
  await expect(page.locator('#otp-form:visible, .otp-input:visible')).toHaveCount(0);
}

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

async function waitForChallenge(page) {
  await expect.poll(async () => {
    if (await hasVisiblePassword(page)) return 'password';
    if (await hasVisibleOtp(page)) return 'otp';
    if (/^\/account\/challenge(?:\/|$)/i.test(pathOf(page))) return 'challenge';
    return 'pending';
  }, {
    message: 'EasyStore should advance from identity entry to an authentication challenge',
    timeout: 20_000,
  }).not.toBe('pending');

  await page.waitForLoadState('domcontentloaded').catch(() => {});
}

async function choosePasswordChallenge(page) {
  if (await hasVisiblePassword(page)) return;

  const controls = page.locator('button:visible, a:visible, [role="button"]:visible');
  const count = await controls.count();
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    const text = ((await control.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
    if (!/password/i.test(text)) continue;
    if (/(forgot|reset|recover)/i.test(text)) continue;

    await control.click();
    await expect(page.locator('input[type="password"]:visible').first()).toBeVisible({ timeout: 15_000 });
    return;
  }

  if (await hasVisibleOtp(page)) {
    throw new Error('EasyStore presented an OTP-only challenge and no password option. The password-based dev test account cannot complete this challenge unattended.');
  }

  throw new Error(`EasyStore challenge at ${pathOf(page)} exposes neither a password field nor a password challenge option.`);
}

async function submitPasswordChallenge(page) {
  const password = page.locator('input[type="password"]:visible').first();
  await expect(password).toBeVisible({ timeout: 15_000 });
  await password.fill(testPassword);

  const form = password.locator('xpath=ancestor::form[1]');
  const submit = form.locator('button[type="submit"]:visible, input[type="submit"]:visible').first();
  if (await visible(submit)) {
    await submit.click();
  } else {
    await password.press('Enter');
  }
}

async function signInThroughEasyStoreIdentityFlow(page) {
  const identity = page.getByRole('textbox', { name: /phone or email|mobile number/i });
  const continueButton = page.getByRole('button', { name: /continue/i });

  await expect(identity).toBeVisible();
  await identity.fill(testUser);
  await expect(continueButton).toBeEnabled();

  await Promise.all([
    waitForChallenge(page),
    continueButton.click(),
  ]);

  await choosePasswordChallenge(page);
  await submitPasswordChallenge(page);
}

async function signIn(page, loginPath = '/account/login') {
  requireTestCredentials();

  const response = await page.goto(loginPath, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  expect(response, 'login navigation should return a response').not.toBeNull();
  expect(response.status(), 'login page should remain reachable').toBeLessThan(500);

  if (await visible(page.locator('#CustomerEmail'))) {
    await signInThroughClassicForm(page);
  } else {
    await signInThroughEasyStoreIdentityFlow(page);
  }

  const deadline = Date.now() + 25_000;
  while (Date.now() < deadline) {
    if (await isFullyAuthenticated(page)) return;
    if (await hasVisibleOtp(page)) {
      throw new Error('EasyStore requested an OTP after password authentication. This test deliberately does not automate OTP delivery; configure the dev test account for password-only authentication or an approved test bypass.');
    }
    await page.waitForTimeout(250);
  }

  throw new Error(`Authentication did not finish; final EasyStore path was ${pathOf(page) || '(unknown)'}.`);
}

async function createAuthenticatedStorageState(browser, baseURL) {
  requireTestCredentials();
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();

  try {
    await signIn(page);
    await expectFullyAuthenticated(page);
    return await context.storageState();
  } finally {
    await context.close();
  }
}

async function openAuthenticatedPage(browser, baseURL, storageState, route) {
  const context = await browser.newContext({ baseURL, storageState });
  const page = await context.newPage();

  try {
    const response = await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    expect(response, `navigation response for ${route}`).not.toBeNull();
    expect(response.status(), `HTTP status for ${route}`).toBeLessThan(400);
    await expectFullyAuthenticated(page, route);
    return { context, page, response };
  } catch (error) {
    await context.close();
    throw error;
  }
}

module.exports = {
  AUTHENTICATING_MARKUP,
  SIGNED_IN_MARKUP,
  createAuthenticatedStorageState,
  expectFullyAuthenticated,
  isFullyAuthenticated,
  openAuthenticatedPage,
  requireTestCredentials,
  signIn,
};

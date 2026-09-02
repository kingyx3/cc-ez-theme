const { expect } = require('@playwright/test');

const testUser = (process.env.EASYSTORE_TEST_USER || '').trim();
const testPassword = process.env.EASYSTORE_TEST_USER_PW || '';
const RECAPTCHA_BLOCKER_CODE = 'EASYSTORE_RECAPTCHA_REQUIRED';

const AUTHENTICATING_PATH = /^\/account\/(?:login|register|recover|auth|challenge|activate|reset)(?:\/|$)/i;
const AUTHENTICATING_MARKUP = [
  '#otp-form',
  '.otp-input',
  'input[autocomplete="one-time-code"]',
  'input[name*="otp" i]',
  'input[name*="code" i]',
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

function passwordInput(page) {
  return page.locator([
    'input[type="password"]:visible',
    'input[name*="password" i]:visible',
    'input[autocomplete="current-password"]:visible',
    'input[autocomplete="new-password"]:visible',
  ].join(', ')).first();
}

async function hasVisibleOtp(page) {
  const explicit = page.locator([
    '#otp-form:visible',
    '.otp-input:visible',
    'input[autocomplete="one-time-code"]:visible',
    'input[name*="otp" i]:visible',
    'input[name*="verification" i]:visible',
    'input[name*="code" i]:visible',
  ].join(', ')).first();
  if (await visible(explicit)) return true;

  // EasyStore has changed OTP markup before. Six single-character numeric/text
  // cells are a stronger contract than any one class name and contain no data.
  const singleCharacterInputs = page.locator('input:visible[maxlength="1"]');
  return (await singleCharacterInputs.count()) >= 4;
}

async function hasVisiblePassword(page) {
  return visible(passwordInput(page));
}

async function hasVisibleRecaptcha(page) {
  const frame = page.locator([
    'iframe[title*="recaptcha" i]:visible',
    'iframe[src*="/recaptcha/" i]:visible',
    'iframe[src*="google.com/recaptcha" i]:visible',
  ].join(', ')).first();
  if (await visible(frame)) return true;

  const mainText = await page.locator('main').first().innerText().catch(() => '');
  return /(not a robot|recaptcha)/i.test(mainText);
}

function isRecaptchaBlockError(error) {
  return String(error instanceof Error ? error.message : error || '').includes(RECAPTCHA_BLOCKER_CODE);
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
  await expect(page.locator('#otp-form:visible, .otp-input:visible, input[autocomplete="one-time-code"]:visible')).toHaveCount(0);
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

function redactDiagnosticText(value) {
  return String(value || '')
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[email]')
    .replace(/\+?\d[\d\s().-]{5,}\d/g, '[number]')
    .replace(/\s+/g, ' ')
    .trim();
}

async function renderedChallengeSurface(page) {
  if (await hasVisiblePassword(page)) return 'password';
  if (await hasVisibleOtp(page)) return 'otp';
  if (await hasVisibleRecaptcha(page)) return 'recaptcha';
  if (!/^\/account\/challenge(?:\/|$)/i.test(pathOf(page))) return 'pending';

  // Header/navigation links are always present on this theme, so they cannot
  // prove that the platform challenge has rendered. Require interaction or
  // challenge-specific copy inside the content/dialog surface instead.
  const scopedInteractive = page.locator([
    'main input:visible',
    'main button:visible',
    'main [role="button"]:visible',
    'main iframe:visible',
    '[role="dialog"] input:visible',
    '[role="dialog"] button:visible',
    '[role="dialog"] [role="button"]:visible',
    '[role="dialog"] iframe:visible',
  ].join(', '));
  if (await scopedInteractive.count()) return 'challenge-ui';

  const mainText = redactDiagnosticText(await page.locator('main').first().innerText().catch(() => ''));
  if (/(password|verification|verify|security code|one[- ]time|otp|challenge|sign in|log in)/i.test(mainText)) {
    return 'challenge-copy';
  }

  return 'pending';
}

async function sanitizedChallengeContract(page) {
  return page.evaluate(() => {
    const clean = value => String(value || '')
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[email]')
      .replace(/\+?\d[\d\s().-]{5,}\d/g, '[number]')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 240);

    const visible = element => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };

    const controlDetails = control => ({
      tag: control.tagName.toLowerCase(),
      type: clean(control.getAttribute('type')),
      name: clean(control.getAttribute('name')),
      ariaLabel: clean(control.getAttribute('aria-label')),
      title: clean(control.getAttribute('title')),
      text: clean(control.textContent),
      hrefPath: control.tagName === 'A' && control.getAttribute('href')
        ? (() => { try { return new URL(control.href).pathname; } catch (_) { return ''; } })()
        : '',
    });

    const main = document.querySelector('main');
    return {
      path: location.pathname,
      mainText: clean(main ? main.textContent : ''),
      inputs: [...document.querySelectorAll('input')].filter(visible).slice(0, 12).map(input => ({
        type: input.type || null,
        name: clean(input.name),
        autocomplete: clean(input.autocomplete),
        inputmode: clean(input.inputMode),
        maxlength: input.maxLength,
        ariaLabel: clean(input.getAttribute('aria-label')),
        placeholder: clean(input.getAttribute('placeholder')),
      })),
      mainControls: main
        ? [...main.querySelectorAll('button, a, [role="button"]')].filter(visible).slice(0, 20).map(controlDetails)
        : [],
      dialogs: [...document.querySelectorAll('[role="dialog"]')].filter(visible).slice(0, 4).map(dialog => ({
        text: clean(dialog.textContent),
        controls: [...dialog.querySelectorAll('button, a, [role="button"]')].filter(visible).slice(0, 12).map(controlDetails),
      })),
      frames: [...document.querySelectorAll('iframe')].filter(visible).slice(0, 6).map(frame => ({
        title: clean(frame.getAttribute('title')),
        name: clean(frame.getAttribute('name')),
        srcPath: (() => { try { return frame.src ? new URL(frame.src).pathname : ''; } catch (_) { return ''; } })(),
        srcOrigin: (() => { try { return frame.src ? new URL(frame.src).origin : ''; } catch (_) { return ''; } })(),
      })),
    };
  });
}

async function waitForChallenge(page) {
  try {
    await expect.poll(() => renderedChallengeSurface(page), {
      message: 'EasyStore should advance from identity entry to a rendered authentication challenge',
      timeout: 20_000,
      intervals: [100, 200, 500, 1000],
    }).not.toBe('pending');
  } catch (error) {
    const contract = await sanitizedChallengeContract(page).catch(() => ({ path: pathOf(page) }));
    throw new Error(`EasyStore challenge surface did not render. Sanitized challenge contract: ${JSON.stringify(contract)}`, { cause: error });
  }

  await page.waitForLoadState('domcontentloaded').catch(() => {});
  await page.waitForTimeout(200);
}

async function clickPasswordMethodIfPresent(page) {
  const accessibleCandidates = [
    page.getByRole('button', { name: /password/i }),
    page.getByRole('link', { name: /password/i }),
    page.locator('[role="button"]:visible').filter({ hasText: /password/i }),
    page.locator('[aria-label*="password" i]:visible, [title*="password" i]:visible'),
  ];

  for (const candidate of accessibleCandidates) {
    const count = await candidate.count();
    for (let index = 0; index < count; index += 1) {
      const control = candidate.nth(index);
      const text = ((await control.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
      const label = (await control.getAttribute('aria-label').catch(() => '')) || '';
      const title = (await control.getAttribute('title').catch(() => '')) || '';
      const descriptor = `${text} ${label} ${title}`;
      if (/(forgot|reset|recover)/i.test(descriptor)) continue;
      await control.click();
      await expect(passwordInput(page)).toBeVisible({ timeout: 15_000 });
      return true;
    }
  }
  return false;
}

async function openAlternateChallengeMethods(page) {
  const alternates = [
    /another (?:way|method)/i,
    /other (?:way|method|option)/i,
    /try another/i,
    /more (?:options|methods)/i,
    /choose (?:another|a different)/i,
  ];

  for (const pattern of alternates) {
    const candidates = page.locator('button:visible, a:visible, [role="button"]:visible').filter({ hasText: pattern });
    if (!(await candidates.count())) continue;
    await candidates.first().click();
    await page.waitForTimeout(200);
    return true;
  }
  return false;
}

async function choosePasswordChallenge(page) {
  if (await hasVisiblePassword(page)) return;

  if (await hasVisibleRecaptcha(page)) {
    throw new Error(
      `${RECAPTCHA_BLOCKER_CODE}: EasyStore requires Google reCAPTCHA before the password challenge on this CI runner. ` +
      'Authenticated tests will not automate or bypass CAPTCHA. Configure an approved dev-only CI authentication mechanism or CAPTCHA exemption, then rerun the trusted workflow.'
    );
  }

  if (await clickPasswordMethodIfPresent(page)) return;

  if (await openAlternateChallengeMethods(page)) {
    if (await hasVisiblePassword(page)) return;
    if (await hasVisibleRecaptcha(page)) {
      throw new Error(
        `${RECAPTCHA_BLOCKER_CODE}: EasyStore requires Google reCAPTCHA before the password challenge on this CI runner. ` +
        'Authenticated tests will not automate or bypass CAPTCHA. Configure an approved dev-only CI authentication mechanism or CAPTCHA exemption, then rerun the trusted workflow.'
      );
    }
    if (await clickPasswordMethodIfPresent(page)) return;
  }

  const contract = await sanitizedChallengeContract(page);
  if (await hasVisibleOtp(page)) {
    throw new Error(`EasyStore presented an OTP challenge and no password option. Sanitized challenge contract: ${JSON.stringify(contract)}`);
  }

  throw new Error(`EasyStore challenge exposes neither a password field nor a password challenge option. Sanitized challenge contract: ${JSON.stringify(contract)}`);
}

async function submitPasswordChallenge(page) {
  const password = passwordInput(page);
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

  const challengeReady = waitForChallenge(page);
  await continueButton.click();
  await challengeReady;

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
  RECAPTCHA_BLOCKER_CODE,
  SIGNED_IN_MARKUP,
  createAuthenticatedStorageState,
  expectFullyAuthenticated,
  isFullyAuthenticated,
  isRecaptchaBlockError,
  openAuthenticatedPage,
  requireTestCredentials,
  signIn,
};

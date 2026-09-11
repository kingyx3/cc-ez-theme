/*
 * Browser regressions for account flows that cannot be completed reliably
 * against the live storefront because Google reCAPTCHA gates authentication.
 *
 * These pages are served entirely by the test. The real theme modules still
 * run, so we can pin the boundaries the theme controls without pretending to
 * test EasyStore's server-side identity rules:
 *
 * - a platform/browser autofill that distributes six OTP digits stays six cells
 *   and produces exactly one platform verification request;
 * - a rejected verification request is never retried by theme code;
 * - login/register password values are submitted once, unchanged, with no
 *   theme-authored HTML pattern;
 * - purchase history never loads during authentication/profile setup, then
 *   resumes immediately after setup and counts established-customer history.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const readTheme = (relativePath) => fs.readFileSync(
  path.join(__dirname, '..', 'theme', relativePath),
  'utf8'
);

const OTP_COPY = readTheme('assets/account-otp-copy.js');
const LIMITS = readTheme('assets/customer-order-limits.js');

const ORIGIN = 'https://cc-auth.test';
const HANDLE = 'the-hobbit-omega-booster-pack';
const HISTORY_PATH = '/account/orders';
const VERIFY_PATH = '/account/auth/verify';
const PASSWORD = 'No-pattern_[Aa1]!?-2026';

const source = (signedIn) => ({
  customerAuthenticated: signedIn ? 1 : 0,
  customerId: signedIn ? '900' : '',
  diagnostics: { ordersSeen: 0, lineItemsSeen: 0 },
  pageProduct: { handle: HANDLE, sku: '', productId: '', variantIds: [] },
  rules: {
    [HANDLE]: {
      maximum: 2,
      purchased: 0,
      cartQuantity: 0,
      allowedCartQuantity: 2,
      remaining: 2,
      loginRequired: signedIn ? 0 : 1,
      cartExceeded: 0,
      refreshAt: '',
      limitWindowLabel: '',
      windowStart: 0,
      message: '',
    },
  },
});

const historyPayload = JSON.stringify({
  customer: '900',
  renderedAt: 0,
  truncated: false,
  tabs: [],
  currentTab: '',
  nextUrl: '',
  lines: [[HANDLE, '', 1, 2, 'order-1', '', 'line-1']],
});

const OTP_CELLS = Array.from({ length: 6 }, () =>
  '<input type="number" class="otp-input" maxlength="1" pattern="[0-9]">'
).join('');

const otpStep = () => `
  <p>Enter the verification code we sent to your mobile.</p>
  <div id="otp-form"><div class="d-flex">${OTP_CELLS}</div></div>
  <a href="#email">Continue with email instead</a>
  <script>
    (() => {
      const cells = Array.from(document.querySelectorAll('.otp-input'));
      const verify = async () => {
        const code = cells.map((cell) => cell.value).join('');
        const response = await fetch('${VERIFY_PATH}', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        });
        window.__verificationResult = {
          status: response.status,
          text: await response.text(),
        };
      };

      cells.forEach((cell, index) => {
        cell.addEventListener('input', () => {
          if (cells.every((input) => input.value !== '')) verify();
        });
        cell.addEventListener('paste', (event) => {
          event.preventDefault();
          const pasted = (event.clipboardData || window.clipboardData).getData('text');
          pasted.split('').forEach((digit, offset) => {
            const target = cells[index + offset];
            if (target) target.value = digit;
          });
          if (cells.every((input) => input.value !== '')) verify();
        });
      });

      // Playwright cannot invoke Android's OS-level SMS autofill. This models
      // the desired browser/platform outcome: one digit is delivered to each
      // EasyStore-owned cell, using native input events, with no theme handoff.
      window.__platformAutofill = (code) => {
        code.split('').forEach((digit, index) => {
          cells[index].value = digit;
          cells[index].dispatchEvent(new InputEvent('input', {
            bubbles: true,
            inputType: 'insertReplacementText',
            data: digit,
          }));
        });
      };
    })();
  </script>`;

const accountForm = (kind) => {
  const action = `/account/${kind}`;
  return `
    <form id="form-${kind}" action="${action}" method="post">
      <input type="text" name="customer[email_or_phone]" value="6591234567" required>
      <input type="password" name="customer[password]" autocomplete="current-password" required>
      <button type="submit">Continue</button>
    </form>`;
};

const productBody = `
  <product-form data-product-handle="${HANDLE}">
    <form action="/cart/add" method="post">
      <input type="hidden" name="id" value="101">
      <input type="number" name="quantity" value="1">
      <div class="form__message hidden"><span class="js-error-content"></span></div>
      <button type="submit" name="add">Add to cart</button>
      <button type="button" data-buy-now>Buy it now</button>
    </form>
  </product-form>`;

const pageBody = (pathname) => {
  if (pathname === '/account/auth' || pathname === '/verify') return otpStep();
  if (pathname === '/account/login') return accountForm('login');
  if (pathname === '/account/register') return accountForm('register');
  if (pathname.startsWith('/products/')) return productBody;
  return '<p>Account setup</p>';
};

const html = ({ pathname, signedIn, profileRequired }) => `<!doctype html>
<html>
  <body class="${signedIn ? 'customer-logged-in ' : ''}template-page">
    ${signedIn
      ? '<a href="/account/logout" data-customer-authenticated="true">Log out</a>'
      : '<a href="/account/login" data-customer-authenticated="false">Log in</a>'}
    ${pageBody(pathname)}
    <script>
      window.ccProfileCompletionRequired = ${profileRequired ? 'true' : 'false'};
      window.customerOrderLimitsV2 = ${JSON.stringify(source(signedIn))};
    </script>
    <script>${LIMITS}</script>
    <script>${OTP_COPY}</script>
  </body>
</html>`;

async function authSite(page, overrides = {}) {
  const scenario = {
    signedIn: true,
    profileRequired: false,
    verifyStatus: 200,
    verifyText: 'verified',
    ...overrides,
  };
  const counts = { verification: 0, history: 0, login: 0, register: 0 };
  const submitted = { login: null, register: null };
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await page.route(`${ORIGIN}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === 'POST' && url.pathname === VERIFY_PATH) {
      counts.verification += 1;
      await route.fulfill({
        status: scenario.verifyStatus,
        contentType: 'text/plain',
        body: scenario.verifyText,
      });
      return;
    }

    if (request.method() === 'POST' && (url.pathname === '/account/login' || url.pathname === '/account/register')) {
      const kind = url.pathname.endsWith('/login') ? 'login' : 'register';
      counts[kind] += 1;
      submitted[kind] = Object.fromEntries(new URLSearchParams(request.postData() || ''));
      await route.fulfill({ contentType: 'text/html', body: '<!doctype html><p>submitted</p>' });
      return;
    }

    if (url.pathname === HISTORY_PATH) {
      counts.history += 1;
      await route.fulfill({
        contentType: 'text/html',
        body: `<!doctype html><script id="customer-order-limit-history" type="application/json">${historyPayload}</script>`,
      });
      return;
    }

    await route.fulfill({
      contentType: 'text/html',
      body: html({
        pathname: url.pathname,
        signedIn: scenario.signedIn,
        profileRequired: scenario.profileRequired,
      }),
    });
  });

  return {
    scenario,
    counts,
    submitted,
    visit: (pathname) => page.goto(`${ORIGIN}${pathname}`),
    settle: async () => {
      await page.waitForTimeout(100);
      expect(errors, 'theme account modules must not throw').toEqual([]);
    },
  };
}

const otpValues = (page) => page.locator('.otp-input').evaluateAll(
  (inputs) => inputs.map((input) => input.value)
);

test.describe('OTP and signup ownership without live reCAPTCHA', () => {
  test('platform-distributed autofill fills all six cells and verifies exactly once', async ({ page }) => {
    const site = await authSite(page);
    await site.visit('/account/auth');

    await page.evaluate(() => window.__platformAutofill('123456'));
    await expect.poll(() => site.counts.verification).toBe(1);
    await site.settle();

    expect(await otpValues(page)).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(site.counts.verification).toBe(1);
    expect(site.counts.history).toBe(0);
    expect(await page.evaluate(() => window.__verificationResult)).toEqual({
      status: 200,
      text: 'verified',
    });
  });

  test('a platform rejection is surfaced once and never retried by theme code', async ({ page }) => {
    const site = await authSite(page, {
      verifyStatus: 409,
      verifyText: 'Customer already exists (phone)',
    });
    await site.visit('/account/auth');

    await page.evaluate(() => {
      const data = new DataTransfer();
      data.setData('text', '654321');
      document.querySelector('.otp-input').dispatchEvent(
        new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true })
      );
    });
    await expect.poll(() => site.counts.verification).toBe(1);
    await site.settle();

    expect(await otpValues(page)).toEqual(['6', '5', '4', '3', '2', '1']);
    expect(site.counts.verification).toBe(1);
    expect(site.counts.history).toBe(0);
    expect(await page.evaluate(() => window.__verificationResult)).toEqual({
      status: 409,
      text: 'Customer already exists (phone)',
    });
  });

  for (const kind of ['login', 'register']) {
    test(`${kind} submits the password once, unchanged, with no browser pattern`, async ({ page }) => {
      const site = await authSite(page, { signedIn: false });
      await site.visit(`/account/${kind}`);

      const password = page.locator('input[name="customer[password]"]');
      await expect(password).not.toHaveAttribute('pattern', /.+/);
      await password.fill(PASSWORD);
      await page.locator(`#form-${kind} button[type="submit"]`).click();
      await expect.poll(() => site.counts[kind]).toBe(1);

      expect(site.counts[kind]).toBe(1);
      expect(site.counts.history).toBe(0);
      expect(site.submitted[kind]['customer[password]']).toBe(PASSWORD);
    });
  }
});

test.describe('theme customer password markup', () => {
  test('customer password inputs do not define a theme-side pattern', async () => {
    const customerTemplates = path.join(__dirname, '..', 'theme', 'templates', 'customers');
    const files = ['login.liquid', 'register.liquid', 'activate_account.liquid', 'reset_password.liquid', 'details.liquid'];
    let fields = 0;

    for (const file of files) {
      const markup = fs.readFileSync(path.join(customerTemplates, file), 'utf8');
      const inputs = markup.match(/<input\b(?=[^>]*\btype="password")[^>]*>/gis) || [];
      fields += inputs.length;
      for (const input of inputs) {
        expect(input, `${file} password field must stay pattern-free`).not.toMatch(/\bpattern\s*=/i);
      }
    }

    expect(fields).toBeGreaterThan(0);
  });
});

test.describe('purchase history is isolated from account setup', () => {
  for (const pathname of [
    '/account/login',
    '/account/register',
    '/account/recover',
    '/account/auth',
    '/account/activate',
    '/account/reset',
    '/verify',
  ]) {
    test(`does not request order history on ${pathname}`, async ({ page }) => {
      const site = await authSite(page, { signedIn: true });
      await site.visit(pathname);
      await site.settle();

      expect(site.counts.history).toBe(0);
      expect(await page.evaluate(() => window.CustomerOrderLimits.historyState())).toBe('unavailable');
    });
  }

  test('required-profile setup suppresses history even on a non-auth path', async ({ page }) => {
    const site = await authSite(page, { signedIn: true, profileRequired: true });
    await site.visit('/account/profile');
    await site.settle();

    expect(site.counts.history).toBe(0);
    expect(await page.evaluate(() => window.CustomerOrderLimits.historyState())).toBe('unavailable');
  });

  test('after setup, established-customer history loads and exhausts the allowance', async ({ page }) => {
    const site = await authSite(page, { signedIn: true });
    await site.visit(`/products/${HANDLE}`);

    await expect.poll(() => page.evaluate(() => window.CustomerOrderLimits.historyState())).toBe('loaded');
    await site.settle();

    expect(site.counts.history).toBe(1);
    expect(await page.evaluate((handle) =>
      window.customerOrderLimitsV2.rules[handle].purchased, HANDLE
    )).toBe(2);
    const violation = await page.evaluate((handle) =>
      window.CustomerOrderLimits.additionViolation(handle, 1), HANDLE
    );
    expect(violation).toMatchObject({
      remaining: 0,
      rule: {
        maximum: 2,
        purchased: 2,
      },
    });
    expect(violation.message).toContain('already ordered 2');
  });
});

/*
 * Runtime guard for the narrow Android OTP handoff.
 *
 * EasyStore still owns verification. The theme may synchronously split one
 * trusted six-digit Android input across the six plain-DOM cells, but it must
 * not cancel that event or manufacture a replacement event. Manual typing,
 * native paste, and already-distributed input remain platform-native.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const OTP_COPY = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'account-otp-copy.js'),
  'utf8'
);
const OTP_AUTOFILL = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'otp-same-event-autofill.js'),
  'utf8'
);

// Leave maxlength off so Playwright can reproduce Android's observed behavior:
// one trusted input inserts all six digits into the first visual cell.
const CELLS = Array.from({ length: 6 }, () =>
  '<input type="number" class="otp-input field__input no-float-label" pattern="[0-9]">'
).join('');

const PAGE = `<!doctype html><html><body>
  <p>Enter the verification code we sent to your mobile.</p>
  <div id="otp-form"><div class="d-flex">${CELLS}</div></div>
  <button id="resend-otp">Resend OTP</button>
  <a id="email-alternative" href="#email">Continue with email instead</a>
</body></html>`;

const installWidget = () => {
  window.__submits = 0;
  window.__submittedCode = null;
  window.__platformInputs = [];

  const otpInputs = Array.from(document.querySelectorAll('.otp-input'));
  const submitOTP = () => {
    window.__submits += 1;
    window.__submittedCode = otpInputs.map((input) => input.value).join('');
  };

  otpInputs.forEach((input, index) => {
    input.addEventListener('input', () => {
      window.__platformInputs.push({
        index,
        code: otpInputs.map((cell) => cell.value).join(''),
      });
      if (index === otpInputs.length - 1) submitOTP();
    });

    input.addEventListener('paste', (event) => {
      event.preventDefault();
      const pasted = (event.clipboardData || window.clipboardData).getData('text');
      if (!pasted) return;
      pasted.split('').forEach((digit, offset) => {
        const cell = otpInputs[index + offset];
        if (cell) cell.value = digit;
      });
      if (otpInputs.every((cell) => cell.value !== '')) submitOTP();
    });
  });

  window.typeCode = (code) => {
    code.split('').forEach((digit, index) => {
      otpInputs[index].value = digit;
      otpInputs[index].dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
};

const state = () => ({
  submits: window.__submits,
  code: window.__submittedCode,
  platformInputs: window.__platformInputs,
  cells: Array.from(document.querySelectorAll('.otp-input')).map((input) => input.value),
  emailAlternativeHidden: document.getElementById('email-alternative').hidden,
});

async function widget(page) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setContent(PAGE);
  await page.evaluate(installWidget);
  await page.evaluate(OTP_COPY);
  await page.evaluate(OTP_AUTOFILL);

  return {
    read: async () => {
      await page.waitForTimeout(50);
      expect(errors, 'OTP helpers must not throw').toEqual([]);
      return page.evaluate(state);
    },
  };
}

test.describe('OTP same-event handoff', () => {
  test('splits one trusted full-code input while EasyStore receives only that original event', async ({ page }) => {
    const w = await widget(page);
    const first = page.locator('.otp-input').first();
    await first.focus();
    await page.keyboard.insertText('123456');
    const got = await w.read();

    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.platformInputs).toEqual([{ index: 0, code: '123456' }]);
    // No synthetic final-cell input was created by the theme.
    expect(got.submits).toBe(0);
  });

  test('leaves manual typing entirely platform-native', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => window.typeCode('112233'));
    const got = await w.read();

    expect(got.cells).toEqual(['1', '1', '2', '2', '3', '3']);
    expect(got.platformInputs.map((entry) => entry.index)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(got.submits).toBe(1);
    expect(got.code).toBe('112233');
  });

  test('leaves native paste entirely platform-native', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => {
      const data = new DataTransfer();
      data.setData('text', '123456');
      document.querySelector('.otp-input').dispatchEvent(
        new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true })
      );
    });
    const got = await w.read();

    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.platformInputs).toEqual([]);
    expect(got.submits).toBe(1);
  });

  test('hides only the email alternative before any OTP interaction', async ({ page }) => {
    const w = await widget(page);
    const got = await w.read();

    expect(got.emailAlternativeHidden).toBe(true);
    expect(got.cells).toEqual(['', '', '', '', '', '']);
    expect(got.platformInputs).toEqual([]);
    expect(got.submits).toBe(0);
  });
});

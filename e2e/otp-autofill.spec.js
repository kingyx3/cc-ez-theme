/*
 * Emergency regression guard for the OTP hotfix.
 *
 * EasyStore owns the live one-time-code widget. While the live signup flow is
 * returning HTML where its client expects JSON, the theme must not write into
 * those cells or dispatch synthetic completion events. This suite runs the
 * shipped compatibility asset against a replica of the captured widget and
 * proves the module is inert while normal platform typing still works.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const MODULE = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'account-otp-autofill.js'),
  'utf8'
);

const CELLS = Array.from({ length: 6 }, () =>
  '<input type="number" class="otp-input field__input no-float-label" maxlength="1" pattern="[0-9]">'
).join('');

const PAGE = `<!doctype html><html><body>
  <div id="otp-form"><div class="d-flex">${CELLS}</div></div>
</body></html>`;

const installWidget = () => {
  window.__submits = 0;
  window.__submittedCode = null;
  const otpInputs = Array.from(document.querySelectorAll('.otp-input'));
  const submitOTP = () => {
    window.__submits += 1;
    window.__submittedCode = otpInputs.map((input) => input.value).join('');
  };
  otpInputs.forEach((input, index) => {
    input.addEventListener('input', () => {
      if (input.value.length >= 1) {
        if (index < otpInputs.length - 1) otpInputs[index + 1].focus();
        if (index === otpInputs.length - 1) submitOTP();
      }
    });
  });
  window.autofill = (code, cellIndex = 0) => {
    otpInputs[cellIndex].value = code;
    otpInputs[cellIndex].dispatchEvent(new Event('input', { bubbles: true }));
  };
  window.typeCode = (code) => {
    code.split('').forEach((digit, index) => {
      otpInputs[index].value = digit;
      otpInputs[index].dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
};

const readState = () => ({
  submits: window.__submits,
  code: window.__submittedCode,
  cells: Array.from(document.querySelectorAll('.otp-input')).map((input) => input.value),
});

async function widget(page) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setContent(PAGE);
  await page.evaluate(installWidget);
  await page.evaluate(MODULE);
  return async () => {
    await page.waitForTimeout(50);
    expect(errors).toEqual([]);
    return page.evaluate(readState);
  };
}

test.describe('OTP theme hotfix', () => {
  test('autofill is left entirely to EasyStore', async ({ page }) => {
    const read = await widget(page);
    await page.evaluate(() => window.autofill('123456'));
    const got = await read();
    expect(got.cells).toEqual(['123456', '', '', '', '', '']);
    expect(got.submits).toBe(0);
  });

  test('manual platform typing still submits once', async ({ page }) => {
    const read = await widget(page);
    await page.evaluate(() => window.typeCode('123456'));
    const got = await read();
    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.submits).toBe(1);
    expect(got.code).toBe('123456');
  });
});

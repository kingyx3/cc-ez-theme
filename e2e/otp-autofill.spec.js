/*
 * Behavioural guard for account-otp-autofill.js.
 *
 * The one-time-code widget belongs to EasyStore, and theme code writing into its
 * cells broke signup twice: verification posted more than once and the second
 * POST came back "Customer already exists (phone)". The invariant that keeps
 * that from happening again is a count, not a shape - the widget must be asked
 * to submit exactly once - so it is asserted by running the real module against
 * a replica of the real widget and counting.
 *
 * The replica is not invented. Its markup comes from
 * scripts/otp-widget-capture.console.js and its handlers are reproduced verbatim
 * from what scripts/otp-handler-probe.console.js printed on the live step, so
 * `submitOTP()` is reachable here by exactly the paths it is reachable by in
 * production. No network and no store account are needed.
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
  <button id="resend-otp">Resend OTP</button>
  <button id="submit-btn" style="display:none">Continue</button>
</body></html>`;

// Reproduced from the probe output. submitOTP is reachable from the last cell's
// input event and from the widget's own paste handler, and from nowhere else.
const installWidget = () => {
  window.__submits = 0;
  window.__submittedCode = null;
  const otp_inputs = Array.from(document.querySelectorAll('.otp-input'));
  const submitOTP = () => {
    window.__submits += 1;
    window.__submittedCode = otp_inputs.map((input) => input.value).join('');
  };
  const displayContinueButton = () => {
    document.getElementById('submit-btn').style.display =
      otp_inputs.every((input) => input.value !== '') ? '' : 'none';
  };
  otp_inputs.forEach((input, index) => {
    input.addEventListener('input', () => {
      if (input.value.length >= 1) {
        if (index < otp_inputs.length - 1) otp_inputs[index + 1].focus();
        if (index === 5) submitOTP();
      }
      displayContinueButton();
    });
    input.addEventListener('focus', () => {
      for (let i = 0; i < otp_inputs.length; i += 1) {
        if (otp_inputs[i].value === '') {
          otp_inputs[i].focus();
          break;
        }
      }
    });
    input.addEventListener('paste', (event) => {
      event.preventDefault();
      const clipboard = event.clipboardData || window.clipboardData;
      const pasted = clipboard.getData('text');
      if (!pasted) return;
      pasted.split('').forEach((digit, i) => {
        if (otp_inputs[index + i]) otp_inputs[index + i].value = digit;
        if ((index + i) === 5 && digit) submitOTP();
        if (index + i < otp_inputs.length - 1) otp_inputs[index + i + 1].focus();
      });
    });
  });
};

const HELPERS = `
  // Android autofill arrives as a plain input event carrying the whole code,
  // which is why maxlength="1" does not contain it on a number input.
  window.autofill = (code, cellIndex = 0) => {
    const cells = document.querySelectorAll('.otp-input');
    cells[cellIndex].value = code;
    cells[cellIndex].dispatchEvent(new Event('input', { bubbles: true }));
  };
  window.typeCode = (code) => {
    const cells = document.querySelectorAll('.otp-input');
    code.split('').forEach((digit, i) => {
      cells[i].value = digit;
      cells[i].dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
`;

const state = () => ({
  submits: window.__submits,
  code: window.__submittedCode,
  cells: Array.from(document.querySelectorAll('.otp-input')).map((input) => input.value),
});

async function widget(page, { withModule = true } = {}) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setContent(PAGE);
  await page.evaluate(installWidget);
  await page.evaluate(HELPERS);
  if (withModule) await page.evaluate(MODULE);
  return {
    read: async () => {
      await page.waitForTimeout(150);
      expect(errors, 'the module must not throw').toEqual([]);
      return page.evaluate(state);
    },
  };
}

test.describe('OTP autofill spreading', () => {
  test('without the module the whole code stays in one cell', async ({ page }) => {
    const w = await widget(page, { withModule: false });
    await page.evaluate(() => window.autofill('123456'));
    const got = await w.read();
    // The bug as reported: six digits in the first cell, five cells empty.
    expect(got.cells).toEqual(['123456', '', '', '', '', '']);
    expect(got.submits).toBe(0);
  });

  test('an autofilled code is spread and submitted exactly once', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => window.autofill('123456'));
    const got = await w.read();
    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.submits).toBe(1);
    expect(got.code).toBe('123456');
  });

  test('a full code landing in a later cell still starts at the first', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => window.autofill('654321', 2));
    const got = await w.read();
    expect(got.cells).toEqual(['6', '5', '4', '3', '2', '1']);
    expect(got.submits).toBe(1);
  });

  test('typing by hand is unaffected and still submits once', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => window.typeCode('112233'));
    const got = await w.read();
    expect(got.submits).toBe(1);
    expect(got.code).toBe('112233');
  });

  test('a short code is spread but never submitted', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => window.autofill('1234'));
    const got = await w.read();
    expect(got.cells).toEqual(['1', '2', '3', '4', '', '']);
    // Submitting here would post an incomplete verification.
    expect(got.submits).toBe(0);
  });

  test('autofill firing twice still submits only once', async ({ page }) => {
    // This is the outage condition: a second POST returns
    // "Customer already exists (phone)" and signup breaks.
    const w = await widget(page);
    await page.evaluate(() => {
      window.autofill('123456');
      window.autofill('123456');
    });
    const got = await w.read();
    expect(got.submits).toBe(1);
  });

  test("the widget's own paste path is left alone", async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => {
      const data = new DataTransfer();
      data.setData('text', '123456');
      document.querySelectorAll('.otp-input')[0].dispatchEvent(
        new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true })
      );
    });
    const got = await w.read();
    expect(got.submits).toBe(1);
    expect(got.code).toBe('123456');
  });

  test('correcting a digit after a submit can submit again', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => window.autofill('123456'));
    await page.waitForTimeout(100);
    await page.evaluate(() => {
      const cells = document.querySelectorAll('.otp-input');
      cells[5].value = '';
      cells[5].dispatchEvent(new Event('input', { bubbles: true }));
      cells[5].value = '9';
      cells[5].dispatchEvent(new Event('input', { bubbles: true }));
    });
    const got = await w.read();
    expect(got.submits).toBe(2);
    expect(got.code).toBe('123459');
  });

  test('inputs outside the widget are ignored', async ({ page }) => {
    const w = await widget(page);
    await page.evaluate(() => {
      const foreign = document.createElement('input');
      foreign.className = 'otp-input';
      document.body.appendChild(foreign);
      foreign.value = '999999';
      foreign.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const got = await w.read();
    expect(got.submits).toBe(0);
    expect(got.cells.slice(0, 6)).toEqual(['', '', '', '', '', '']);
  });
});

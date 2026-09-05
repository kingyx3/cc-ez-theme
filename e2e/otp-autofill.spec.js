/*
 * Runtime guard for the Android six-digits-in-one-cell OTP regression.
 *
 * The important invariant is not just the final values. EasyStore owns the
 * verification request, so it must observe one completed input event total.
 * These replicas cover both the handler captured from the live widget and the
 * platform change that made the August implementation unsafe.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const MODULE = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'account-otp-copy.js'),
  'utf8'
);

const CELLS = Array.from({ length: 6 }, () =>
  '<input type="number" class="otp-input field__input no-float-label" maxlength="1" pattern="[0-9]">'
).join('');

const PAGE = `<!doctype html><html><body>
  <div id="otp-form"><div class="d-flex">${CELLS}</div></div>
  <button id="resend-otp">Resend OTP</button>
</body></html>`;

const installWidget = (mode) => {
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

      if (mode === 'last-cell') {
        if (index === otpInputs.length - 1) submitOTP();
        return;
      }

      // Models the platform change that invalidated the August assumption: any
      // input event can complete verification once all visible cells are full.
      if (mode === 'any-complete' && otpInputs.every((cell) => cell.value !== '')) {
        submitOTP();
      }
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
};

const installHelpers = () => {
  window.autofill = (code, cellIndex = 0) => {
    const cells = document.querySelectorAll('.otp-input');
    cells[cellIndex].value = code;
    cells[cellIndex].dispatchEvent(new Event('input', { bubbles: true }));
  };

  window.typeCode = (code) => {
    const cells = document.querySelectorAll('.otp-input');
    code.split('').forEach((digit, index) => {
      cells[index].value = digit;
      cells[index].dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
};

const state = () => ({
  submits: window.__submits,
  code: window.__submittedCode,
  platformInputs: window.__platformInputs,
  cells: Array.from(document.querySelectorAll('.otp-input')).map((input) => input.value),
});

async function widget(page, mode = 'last-cell', beforeModule = null) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setContent(PAGE);
  await page.evaluate(installWidget, mode);
  await page.evaluate(installHelpers);
  if (beforeModule) await page.evaluate(beforeModule);
  await page.evaluate(MODULE);

  return {
    read: async () => {
      await page.waitForTimeout(50);
      expect(errors, 'OTP helper must not throw').toEqual([]);
      return page.evaluate(state);
    },
  };
}

test.describe('OTP autofill single platform event', () => {
  test('spreads six digits and hands the captured last-cell widget one completion event', async ({ page }) => {
    const w = await widget(page, 'last-cell');
    await page.evaluate(() => window.autofill('123456'));
    const got = await w.read();

    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.platformInputs).toEqual([{ index: 5, code: '123456' }]);
    expect(got.submits).toBe(1);
    expect(got.code).toBe('123456');
  });

  test('still submits once when the platform submits on any completed input', async ({ page }) => {
    const w = await widget(page, 'any-complete');
    await page.evaluate(() => window.autofill('123456'));
    const got = await w.read();

    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.platformInputs).toEqual([{ index: 5, code: '123456' }]);
    expect(got.submits).toBe(1);
  });

  test('a repeated autofill event never reaches the platform twice', async ({ page }) => {
    const w = await widget(page, 'any-complete');
    await page.evaluate(() => {
      window.autofill('123456');
      window.autofill('123456');
    });
    const got = await w.read();

    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.platformInputs).toEqual([{ index: 5, code: '123456' }]);
    expect(got.submits).toBe(1);
  });

  test('a full code landing in a later cell is normalized before the single handoff', async ({ page }) => {
    const w = await widget(page, 'any-complete');
    await page.evaluate(() => window.autofill('654321', 2));
    const got = await w.read();

    expect(got.cells).toEqual(['6', '5', '4', '3', '2', '1']);
    expect(got.platformInputs).toEqual([{ index: 5, code: '654321' }]);
    expect(got.submits).toBe(1);
  });

  test('manual typing remains entirely platform-native', async ({ page }) => {
    const w = await widget(page, 'any-complete');
    await page.evaluate(() => window.typeCode('112233'));
    const got = await w.read();

    expect(got.cells).toEqual(['1', '1', '2', '2', '3', '3']);
    expect(got.platformInputs.map((entry) => entry.index)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(got.submits).toBe(1);
    expect(got.code).toBe('112233');
  });

  test('native paste remains entirely platform-native', async ({ page }) => {
    const w = await widget(page, 'last-cell');
    await page.evaluate(() => {
      const data = new DataTransfer();
      data.setData('text', '123456');
      document.querySelectorAll('.otp-input')[0].dispatchEvent(
        new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true })
      );
    });
    const got = await w.read();

    expect(got.cells).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(got.platformInputs).toEqual([]);
    expect(got.submits).toBe(1);
  });

  test('partial multi-digit input is left alone', async ({ page }) => {
    const w = await widget(page, 'any-complete');
    await page.evaluate(() => window.autofill('1234'));
    const got = await w.read();

    expect(got.cells).toEqual(['1234', '', '', '', '', '']);
    expect(got.platformInputs).toEqual([{ index: 0, code: '1234' }]);
    expect(got.submits).toBe(0);
  });

  test('framework-controlled cells fail closed with no synthetic handoff', async ({ page }) => {
    const w = await widget(page, 'last-cell', () => {
      document.querySelectorAll('.otp-input')[0].__reactFiber$probe = {};
    });
    await page.evaluate(() => window.autofill('123456'));
    const got = await w.read();

    expect(got.cells).toEqual(['123456', '', '', '', '', '']);
    expect(got.platformInputs).toEqual([{ index: 0, code: '123456' }]);
    expect(got.submits).toBe(0);
  });
});

const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const ACCOUNT_PHONE = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'account-phone-input.js'),
  'utf8'
);

const pageHtml = () => `<!doctype html>
<html>
  <head><meta charset="utf-8"></head>
  <body>
    <form id="mobile-auth" action="/account/register" method="post">
      <input type="hidden" name="_token" value="csrf-test-token">
      <div class="insert-code-shell">
        <input
          id="insert-code-phone"
          name="customer[email_or_phone]"
          data-es-mobile-only="true"
          placeholder="Enter your mobile number"
          aria-label="Mobile number"
          inputmode="tel"
          required
        >
      </div>
      <button type="submit">Continue</button>
    </form>

    <script>
      window.__insertCodeBlocked = false;
      window.__frameworkPhone = '';
      window.__clickStatePhone = null;
      window.__submittedPhone = null;
      window.__submittedFrameworkPhone = null;
      window.__submittedAction = null;
      window.__submittedName = null;

      var phone = document.getElementById('insert-code-phone');
      phone.addEventListener('input', function () {
        window.__frameworkPhone = phone.value;
      });

      // Mirrors the important part of the store's Insert Code click guard:
      // an 8-digit SG number or an already-international + number is accepted.
      // Capture framework state here too, like app/reCAPTCHA click logic would.
      document.addEventListener('click', function (event) {
        var input = document.querySelector('input[data-es-mobile-only="true"]');
        var button = event.target.closest && event.target.closest('button[type="submit"]');
        if (!button) return;
        window.__clickStatePhone = window.__frameworkPhone;
        if (!input) return;
        var value = String(input.value || '').trim();
        if (!/^\\d{8}$/.test(value) && !/^\\+[1-9]\\d{6,14}$/.test(value)) {
          window.__insertCodeBlocked = true;
          event.preventDefault();
          event.stopImmediatePropagation();
        }
      }, true);

      document.getElementById('mobile-auth').addEventListener('submit', function (event) {
        event.preventDefault();
        var input = document.getElementById('insert-code-phone');
        window.__submittedPhone = input.value;
        window.__submittedFrameworkPhone = window.__frameworkPhone;
        window.__submittedAction = event.currentTarget.getAttribute('action');
        window.__submittedName = input.getAttribute('name');
      });
    </script>
    <script>${ACCOUNT_PHONE}</script>
  </body>
</html>`;

test.describe('international account phone UI with Insert Code', () => {
  test('enhances and aligns the live mobile-only field without changing its EasyStore contract', async ({ page }) => {
    await page.setContent(pageHtml());

    const country = page.locator('[data-phone-country-select]');
    const phone = page.locator('#insert-code-phone');
    const form = page.locator('#mobile-auth');

    await expect(country).toBeVisible();
    await expect(country).toHaveValue('SG');
    await expect(phone).toHaveAttribute('data-cc-phone-owned', 'true');
    await expect(phone).not.toHaveAttribute('data-es-mobile-only', 'true');
    await expect(phone).toHaveAttribute('placeholder', 'Mobile number');
    await expect(phone).toHaveAttribute('name', 'customer[email_or_phone]');
    await expect(form).toHaveAttribute('action', '/account/register');
    await expect(form.locator('input[name="_token"]')).toHaveValue('csrf-test-token');
    await expect(page.locator('.account-phone-input')).toBeVisible();

    const countryBox = await country.boundingBox();
    const phoneBox = await phone.boundingBox();
    expect(countryBox).not.toBeNull();
    expect(phoneBox).not.toBeNull();
    expect(Math.abs(countryBox.y - phoneBox.y)).toBeLessThanOrEqual(1);
    expect(Math.abs(countryBox.height - phoneBox.height)).toBeLessThanOrEqual(1);
  });

  test('foreign local number reaches app state before click and submits through the original EasyStore form', async ({ page }) => {
    await page.setContent(pageHtml());

    await page.locator('[data-phone-country-select]').selectOption('MY');
    await page.locator('#insert-code-phone').fill('0123456789');
    await expect.poll(() => page.evaluate(() => window.__frameworkPhone)).toBe('0123456789');

    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__clickStatePhone)).toBe('+60123456789');
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('+60123456789');
    await expect.poll(() => page.evaluate(() => window.__submittedFrameworkPhone)).toBe('+60123456789');
    await expect.poll(() => page.evaluate(() => window.__submittedAction)).toBe('/account/register');
    await expect.poll(() => page.evaluate(() => window.__submittedName)).toBe('customer[email_or_phone]');
  });

  test('Singapore keeps the existing eight-digit local identity shape', async ({ page }) => {
    await page.setContent(pageHtml());

    await page.locator('#insert-code-phone').fill('81234567');
    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__clickStatePhone)).toBe('81234567');
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('81234567');
    await expect.poll(() => page.evaluate(() => window.__submittedFrameworkPhone)).toBe('81234567');
  });
});

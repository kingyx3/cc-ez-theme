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
      window.__submittedPhone = null;

      // Mirrors the important part of the store's Insert Code click guard:
      // an 8-digit SG number or an already-international + number is accepted.
      document.addEventListener('click', function (event) {
        var input = document.querySelector('input[data-es-mobile-only="true"]');
        var button = event.target.closest && event.target.closest('button[type="submit"]');
        if (!input || !button) return;
        var value = String(input.value || '').trim();
        if (!/^\\d{8}$/.test(value) && !/^\\+[1-9]\\d{6,14}$/.test(value)) {
          window.__insertCodeBlocked = true;
          event.preventDefault();
          event.stopImmediatePropagation();
        }
      }, true);

      document.getElementById('mobile-auth').addEventListener('submit', function (event) {
        event.preventDefault();
        window.__submittedPhone = document.getElementById('insert-code-phone').value;
      });
    </script>
    <script>${ACCOUNT_PHONE}</script>
  </body>
</html>`;

test.describe('international account phone UI with Insert Code', () => {
  test('enhances the live mobile-only field even without a theme .field wrapper', async ({ page }) => {
    await page.setContent(pageHtml());

    const country = page.locator('[data-phone-country-select]');
    const phone = page.locator('#insert-code-phone');

    await expect(country).toBeVisible();
    await expect(country).toHaveValue('SG');
    await expect(phone).toHaveAttribute('data-cc-phone-owned', 'true');
    await expect(phone).not.toHaveAttribute('data-es-mobile-only', 'true');
    await expect(phone).toHaveAttribute('placeholder', 'Mobile number');
    await expect(page.locator('.account-phone-input')).toBeVisible();
  });

  test('foreign local number is combined before the Insert Code click guard can reject it', async ({ page }) => {
    await page.setContent(pageHtml());

    await page.locator('[data-phone-country-select]').selectOption('MY');
    await page.locator('#insert-code-phone').fill('0123456789');
    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('+60123456789');
  });

  test('Singapore keeps the existing eight-digit local identity shape', async ({ page }) => {
    await page.setContent(pageHtml());

    await page.locator('#insert-code-phone').fill('81234567');
    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('81234567');
  });
});

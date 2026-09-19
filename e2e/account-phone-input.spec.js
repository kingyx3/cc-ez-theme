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
      <input type="hidden" name="_token" value="csrf-token">
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
      window.__controlledPhone = '';
      window.__submitAction = null;
      window.__submitName = null;

      document.addEventListener('input', function (event) {
        if (event.target && event.target.id === 'insert-code-phone') {
          window.__controlledPhone = event.target.value;
        }
      }, true);

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
        var input = document.getElementById('insert-code-phone');
        window.__submittedPhone = input.value;
        window.__submitAction = event.currentTarget.getAttribute('action');
        window.__submitName = input.getAttribute('name');
      });
    </script>
    <script>${ACCOUNT_PHONE}</script>
  </body>
</html>`;

const detailsHtml = (verified) => `<!doctype html>
<html>
  <head><meta charset="utf-8"></head>
  <body>
    <form id="details_form" action="/account/details" method="post">
      <input type="hidden" name="_token" value="csrf-token">
      <div class="field">
        <input id="DetailPhone" name="details[phone]" value="6582230039" placeholder="Phone">
        <input
          type="hidden"
          name="details[country_code]"
          value="SG"
          data-phone-country-code
          data-phone-input-id="DetailPhone"
          data-phone-verified="${verified ? 'true' : 'false'}"
        >
        <label for="DetailPhone">Phone</label>
      </div>
      <button type="submit">Submit</button>
    </form>
    <script>
      window.__detailsPhone = null;
      window.__detailsCountry = null;
      document.getElementById('details_form').addEventListener('submit', function (event) {
        event.preventDefault();
        window.__detailsPhone = document.getElementById('DetailPhone').value;
        window.__detailsCountry = document.querySelector('[name="details[country_code]"]').value;
      });
    </script>
    <script>${ACCOUNT_PHONE}</script>
  </body>
</html>`;

test.describe('international account phone UI with Insert Code', () => {
  test('enhances and exactly aligns the live mobile-only controls', async ({ page }) => {
    await page.setContent(pageHtml());

    const country = page.locator('[data-phone-country-select]');
    const phone = page.locator('#insert-code-phone');

    await expect(country).toBeVisible();
    await expect(country).toHaveValue('SG');
    await expect(phone).toHaveAttribute('data-cc-phone-owned', 'true');
    await expect(phone).not.toHaveAttribute('data-es-mobile-only', 'true');
    await expect(phone).toHaveAttribute('placeholder', 'Mobile number');

    const countryBox = await country.boundingBox();
    const phoneBox = await phone.boundingBox();
    expect(countryBox).not.toBeNull();
    expect(phoneBox).not.toBeNull();
    expect(Math.abs(countryBox.y - phoneBox.y)).toBeLessThanOrEqual(1);
    expect(Math.abs(countryBox.height - phoneBox.height)).toBeLessThanOrEqual(1);
  });

  test('foreign local number reaches EasyStore controlled state and original endpoint contract', async ({ page }) => {
    await page.setContent(pageHtml());

    await page.locator('[data-phone-country-select]').selectOption('MY');
    await page.locator('#insert-code-phone').fill('0123456789');
    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__controlledPhone)).toBe('+60123456789');
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('+60123456789');
    await expect.poll(() => page.evaluate(() => window.__submitAction)).toBe('/account/register');
    await expect.poll(() => page.evaluate(() => window.__submitName)).toBe('customer[email_or_phone]');
  });

  test('Singapore keeps the existing eight-digit local identity shape', async ({ page }) => {
    await page.setContent(pageHtml());

    await page.locator('#insert-code-phone').fill('81234567');
    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('81234567');
  });

  test('OTP-verified account phone is locked and restored before profile submit', async ({ page }) => {
    await page.setContent(detailsHtml(true));

    const country = page.locator('[data-phone-country-select]');
    const phone = page.locator('#DetailPhone');

    await expect(phone).toHaveAttribute('readonly', '');
    await expect(phone).toHaveAttribute('data-verified-phone-locked', 'true');
    await expect(country).toBeDisabled();

    await page.evaluate(() => {
      const phone = document.getElementById('DetailPhone');
      phone.removeAttribute('readonly');
      phone.value = '99999999';
      document.querySelector('[name="details[country_code]"]').value = 'MY';
    });
    await page.getByRole('button', { name: 'Submit' }).click();

    await expect.poll(() => page.evaluate(() => window.__detailsPhone)).toBe('6582230039');
    await expect.poll(() => page.evaluate(() => window.__detailsCountry)).toBe('SG');
  });

  test('unverified account phone remains editable', async ({ page }) => {
    await page.setContent(detailsHtml(false));

    const country = page.locator('[data-phone-country-select]');
    const phone = page.locator('#DetailPhone');

    await expect(phone).not.toHaveAttribute('readonly', '');
    await expect(phone).not.toHaveAttribute('data-verified-phone-locked', 'true');
    await expect(country).toBeEnabled();
  });
});

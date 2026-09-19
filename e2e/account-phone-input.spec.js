const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const ACCOUNT_PHONE = fs.readFileSync(
  path.join(__dirname, '..', 'theme', 'assets', 'account-phone-input.js'),
  'utf8'
);

const authHtml = () => `<!doctype html>
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
      window.__inputEvents = 0;

      document.getElementById('insert-code-phone').addEventListener('input', function () {
        window.__inputEvents += 1;
      });

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

const detailsHtml = (verified) => `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <style>
      :root { --color-foreground: 0,0,0; }
      .field { position: relative; width: 100%; }
      .field input, select { width: 100%; box-sizing: border-box; height: 4rem; }
    </style>
  </head>
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

test.describe('EasyStore auth phone ownership', () => {
  test('theme helper does not enhance or rewrite the Insert Code auth field', async ({ page }) => {
    await page.setContent(authHtml());

    const phone = page.locator('#insert-code-phone');
    await expect(page.locator('[data-phone-country-select]')).toHaveCount(0);
    await expect(phone).toHaveAttribute('data-es-mobile-only', 'true');
    await expect(phone).not.toHaveAttribute('data-cc-phone-owned');
    await expect(phone).toHaveAttribute('placeholder', 'Enter your mobile number');
    expect(await page.evaluate(() => window.__inputEvents)).toBe(0);
  });

  test('Singapore identity reaches EasyStore exactly as the customer entered it', async ({ page }) => {
    await page.setContent(authHtml());

    await page.locator('#insert-code-phone').fill('81234567');
    const beforeClickEvents = await page.evaluate(() => window.__inputEvents);
    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('81234567');
    expect(await page.evaluate(() => window.__inputEvents)).toBe(beforeClickEvents);
  });

  test('explicit international identity reaches EasyStore unchanged', async ({ page }) => {
    await page.setContent(authHtml());

    await page.locator('#insert-code-phone').fill('+60123456789');
    const beforeClickEvents = await page.evaluate(() => window.__inputEvents);
    await page.getByRole('button', { name: 'Continue' }).click();

    await expect.poll(() => page.evaluate(() => window.__insertCodeBlocked)).toBe(false);
    await expect.poll(() => page.evaluate(() => window.__submittedPhone)).toBe('+60123456789');
    expect(await page.evaluate(() => window.__inputEvents)).toBe(beforeClickEvents);
  });
});

test.describe('account details international phone UI', () => {
  test('country selector and phone input are exactly aligned', async ({ page }) => {
    await page.setContent(detailsHtml(false));

    const country = page.locator('[data-phone-country-select]');
    const phone = page.locator('#DetailPhone');

    await expect(country).toBeVisible();
    const countryBox = await country.boundingBox();
    const phoneBox = await phone.boundingBox();
    expect(countryBox).not.toBeNull();
    expect(phoneBox).not.toBeNull();
    expect(Math.abs(countryBox.y - phoneBox.y)).toBeLessThanOrEqual(1);
    expect(Math.abs(countryBox.height - phoneBox.height)).toBeLessThanOrEqual(1);
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

const fs = require('fs');
const path = require('path');
const { expect } = require('./fixtures');

const LIMIT_CONFIG = path.join(__dirname, '..', 'theme', 'snippets', 'customer-order-limit-config.liquid');
const LIMIT_ROW = /\{% include 'customer-order-limit-row', limit_handle: '([^']*)', limit_maximum: (\d+)/g;

// Which products carry a limit is theme configuration, so the suite reads it
// rather than naming a product of its own. A hardcoded SKU went stale as soon
// as the catalog moved on, and the E2E run failed for a product that was
// simply retired rather than for anything wrong with the theme.
function configuredLimitHandles() {
  const config = fs.readFileSync(LIMIT_CONFIG, 'utf8');
  const handles = [];
  for (const [, handle, maximum] of config.matchAll(LIMIT_ROW)) {
    if (handle && Number(maximum) > 0) handles.push(handle.toLowerCase());
  }
  return handles;
}

// Collections known to carry limited products, used only when a configured
// handle does not resolve as a bare product URL.
const limitedProductCollections = [
  '/collections/late-night-crackers',
  '/collections/the-hobbit',
  '/collections/feature-on-homepage',
];

const limitedProductCandidates = process.env.E2E_LIMITED_PRODUCT_PATH
  ? [process.env.E2E_LIMITED_PRODUCT_PATH]
  : configuredLimitHandles().map(handle => `/products/${handle}`);
const searchTerm = process.env.E2E_SEARCH_TERM || 'Hobbit';

async function gotoStorefront(page, path) {
  const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
  expect(response, `navigation response for ${path}`).not.toBeNull();
  expect(response.status(), `HTTP status for ${path}`).toBeLessThan(500);
  await expect(page.locator('body')).toBeVisible();
  return response;
}

async function expectBasicPageHealth(page) {
  await expect(page).toHaveTitle(/.+/);
  await expect(page.locator('header').first()).toBeVisible();
  await expect(page.locator('footer').first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, 'page should not horizontally overflow the viewport').toBeLessThanOrEqual(2);
}

// Chromium can reach DOMContentLoaded before the deferred product runtime has
// upgraded <product-form>. Clicking at that moment exercises the browser's
// native form path instead of the EasyStore Ajax cart path and makes cart.json
// appear unchanged. Wait for the exact runtime the shopper uses before
// classifying a product or clicking Add to Cart.
async function waitForProductRuntime(page) {
  await page.waitForFunction(() => {
    const form = document.querySelector('product-form form[action="/cart/add"]');
    const host = form && form.closest('product-form');
    const productFormReady = Boolean(form && host && host.form === form);
    const cartRuntimeReady = typeof window.EasyStore?.Action?.addToCart === 'function';

    // customer-order-limits.js intentionally does not create an API on pages
    // with no configured rules. If rules are present, however, wait until its
    // API exists so a fast browser cannot misclassify a limited product as an
    // unlimited one merely because the deferred script has not executed yet.
    const source = window.customerOrderLimitsV2;
    const hasRules = Boolean(source?.rules && Object.keys(source.rules).length);
    const limitsReady = !hasRules || typeof window.CustomerOrderLimits?.ruleFor === 'function';

    return productFormReady && cartRuntimeReady && limitsReady;
  }, null, { timeout: 15_000 });
}

async function readCart(page) {
  return page.evaluate(async () => {
    const response = await fetch('/cart.json', {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(`cart.json returned ${response.status}`);

    const payload = await response.json();
    const cart = Object.prototype.hasOwnProperty.call(payload, 'cart') ? payload.cart : payload;
    if (!cart) return { item_count: 0, items: [] };

    return {
      ...cart,
      item_count: Number(cart.item_count || 0),
      items: Array.isArray(cart.items) ? cart.items : [],
    };
  });
}

async function productLinksFromCollection(page, collectionPath) {
  await gotoStorefront(page, collectionPath);
  const hrefs = await page.locator('a[href*="/products/"]').evaluateAll(nodes =>
    [...new Set(nodes.map(node => node.getAttribute('href')).filter(Boolean))]
  );
  return hrefs.slice(0, 10);
}

async function productHasActiveLimit(page, handle) {
  await waitForProductRuntime(page);
  return page.evaluate(productHandle => {
    const source = window.customerOrderLimitsV2;
    const hasRules = Boolean(source?.rules && Object.keys(source.rules).length);
    if (!hasRules) return false;
    if (typeof window.CustomerOrderLimits?.ruleFor !== 'function') {
      throw new Error('CustomerOrderLimits API did not initialize for a product that publishes limit rules.');
    }
    return Boolean(window.CustomerOrderLimits.ruleFor(productHandle));
  }, handle);
}

async function openUnlimitedPurchasableProduct(page) {
  const collections = [
    '/collections/marvel-super-heroes',
    '/collections/secrets-of-strixhaven',
    '/collections/feature-on-homepage',
  ];

  for (const collection of collections) {
    const links = await productLinksFromCollection(page, collection);
    for (const href of links) {
      await gotoStorefront(page, href);
      const form = page.locator('form[action="/cart/add"]').first();
      const add = page.locator('#AddToCart').first();
      if (!(await form.count()) || !(await add.count())) continue;
      if (await add.isDisabled()) continue;

      await waitForProductRuntime(page);
      const handle = new URL(page.url()).pathname.match(/\/products\/([^/?#]+)/)?.[1] || '';
      if (!handle) continue;
      if (!(await productHasActiveLimit(page, handle))) return href;
    }
  }

  throw new Error('Could not find an in-stock unlimited product in the configured collections. Set E2E_UNLIMITED_PRODUCT_PATH to a known product if the catalog changes.');
}

async function isLimitedProductPage(page) {
  if (!(await page.locator('form[action="/cart/add"]').first().count())) return false;
  const handle = new URL(page.url()).pathname.match(/\/products\/([^/?#]+)/)?.[1] || '';
  if (!handle) return false;
  return productHasActiveLimit(page, handle);
}

// Opens a product the storefront actually publishes a limit rule for, and
// returns its path. The configured handles are tried first; a store that does
// not serve a bare `/products/<handle>` URL falls back to the collections that
// carry limited products.
async function openLimitedProduct(page) {
  for (const candidate of limitedProductCandidates) {
    await gotoStorefront(page, candidate);
    if (await isLimitedProductPage(page)) return candidate;
  }

  for (const collection of limitedProductCollections) {
    for (const href of await productLinksFromCollection(page, collection)) {
      await gotoStorefront(page, href);
      if (await isLimitedProductPage(page)) return href;
    }
  }

  throw new Error(`Could not open a product publishing a purchase-limit rule. Tried ${limitedProductCandidates.join(', ')} and the collections ${limitedProductCollections.join(', ')}. Set E2E_LIMITED_PRODUCT_PATH to a known limited product if the catalog changes.`);
}

async function openConfiguredUnlimitedProduct(page) {
  if (process.env.E2E_UNLIMITED_PRODUCT_PATH) {
    await gotoStorefront(page, process.env.E2E_UNLIMITED_PRODUCT_PATH);
    await waitForProductRuntime(page);

    const handle = new URL(page.url()).pathname.match(/\/products\/([^/?#]+)/)?.[1] || '';
    expect(handle, 'configured unlimited product should resolve to a product route').not.toBe('');
    expect(await productHasActiveLimit(page, handle), 'E2E_UNLIMITED_PRODUCT_PATH must not carry an active customer limit').toBe(false);
    await expect(page.locator('#AddToCart').first()).toBeEnabled();
    return process.env.E2E_UNLIMITED_PRODUCT_PATH;
  }
  return openUnlimitedPurchasableProduct(page);
}

async function addCurrentProductToCart(page) {
  await waitForProductRuntime(page);
  const before = await readCart(page);
  const beforeCount = Number(before?.item_count || 0);
  const add = page.locator('#AddToCart').first();
  await expect(add).toBeVisible();
  await expect(add).toBeEnabled();
  await add.click();

  try {
    await expect.poll(async () => Number((await readCart(page))?.item_count || 0), {
      message: 'cart.json should reflect the added product',
      timeout: 15_000,
    }).toBeGreaterThan(beforeCount);
  } catch (error) {
    const form = page.locator('form[action="/cart/add"]').first();
    const visibleError = form.locator('.form__message:not(.hidden), [role="alert"]:visible').first();
    const message = (await visibleError.textContent().catch(() => ''))?.replace(/\s+/g, ' ').trim();
    const suffix = message ? ` Storefront error: ${message}` : '';
    throw new Error(`Add to Cart did not mutate cart.json within 15 seconds.${suffix}`, { cause: error });
  }

  return readCart(page);
}

async function removeFirstCartItem(page) {
  await gotoStorefront(page, '/cart');
  const cart = await readCart(page);
  expect(cart?.items?.length || 0, 'cart should contain an item before it is removed').toBeGreaterThan(0);

  const accessibleRemove = page.getByRole('button', { name: /^remove\b/i }).first();
  if (await accessibleRemove.count()) {
    await accessibleRemove.click();
  } else {
    const legacyRemove = page.getByText('Remove', { exact: true }).first();
    await expect(legacyRemove).toBeVisible();
    await legacyRemove.click();
  }

  await expect.poll(async () => Number((await readCart(page))?.item_count || 0), {
    message: 'cart item count should become zero after Remove',
    timeout: 15_000,
  }).toBe(0);

  return readCart(page);
}

module.exports = {
  addCurrentProductToCart,
  configuredLimitHandles,
  expectBasicPageHealth,
  gotoStorefront,
  openConfiguredUnlimitedProduct,
  openLimitedProduct,
  readCart,
  removeFirstCartItem,
  searchTerm,
  waitForProductRuntime,
};

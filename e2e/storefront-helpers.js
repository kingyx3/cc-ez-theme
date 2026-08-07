const { expect } = require('./fixtures');

const limitedProductPath = process.env.E2E_LIMITED_PRODUCT_PATH
  || '/collections/feature-on-homepage/products/mtg-hob-cbb-en-pack';
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

async function readCart(page) {
  return page.evaluate(async () => {
    const response = await fetch('/cart.json', {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(`cart.json returned ${response.status}`);
    const payload = await response.json();
    return payload.cart || payload;
  });
}

async function productLinksFromCollection(page, collectionPath) {
  await gotoStorefront(page, collectionPath);
  const hrefs = await page.locator('a[href*="/products/"]').evaluateAll(nodes =>
    [...new Set(nodes.map(node => node.getAttribute('href')).filter(Boolean))]
  );
  return hrefs.slice(0, 10);
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
      const handle = new URL(page.url()).pathname.match(/\/products\/([^/?#]+)/)?.[1] || '';
      const limited = await page.evaluate(productHandle => Boolean(window.CustomerOrderLimits?.ruleFor?.(productHandle)), handle);
      if (!limited) return href;
    }
  }

  throw new Error('Could not find an in-stock unlimited product in the configured collections. Set E2E_UNLIMITED_PRODUCT_PATH to a known product if the catalog changes.');
}

async function openConfiguredUnlimitedProduct(page) {
  if (process.env.E2E_UNLIMITED_PRODUCT_PATH) {
    await gotoStorefront(page, process.env.E2E_UNLIMITED_PRODUCT_PATH);
    return process.env.E2E_UNLIMITED_PRODUCT_PATH;
  }
  return openUnlimitedPurchasableProduct(page);
}

async function addCurrentProductToCart(page) {
  const before = await readCart(page);
  const beforeCount = Number(before?.item_count || 0);
  const add = page.locator('#AddToCart').first();
  await expect(add).toBeVisible();
  await expect(add).toBeEnabled();
  await add.click();

  await expect.poll(async () => Number((await readCart(page))?.item_count || 0), {
    message: 'cart.json should reflect the added product',
  }).toBeGreaterThan(beforeCount);

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
  expectBasicPageHealth,
  gotoStorefront,
  limitedProductPath,
  openConfiguredUnlimitedProduct,
  readCart,
  removeFirstCartItem,
  searchTerm,
};

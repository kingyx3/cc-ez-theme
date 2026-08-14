const { test, expect } = require('./fixtures');
const {
  addCurrentProductToCart,
  expectBasicPageHealth,
  gotoStorefront,
  limitedProductPath,
  openConfiguredUnlimitedProduct,
  readCart,
  removeFirstCartItem,
  searchTerm,
} = require('./storefront-helpers');

test.describe('storefront navigation and discovery', () => {
  test('homepage renders the configured shell and announcement', async ({ page }) => {
    await gotoStorefront(page, '/');
    await expectBasicPageHealth(page);
    await expect(page.locator('.header__heading-link').first()).toBeVisible();
    await expect(page.locator('.announcement-bar').first()).toBeVisible();
  });

  test('desktop and mobile primary navigation are usable', async ({ page }) => {
    await gotoStorefront(page, '/');
    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();

    if (viewport.width < 990) {
      const menu = page.locator('.header__icon--menu').first();
      await expect(menu).toBeVisible();
      await menu.click();
      await expect(page.locator('#menu-drawer')).toBeVisible();
      await expect(page.locator('#menu-drawer a[href="/collections/the-hobbit"]:visible').first()).toBeVisible();
    } else {
      const desktopNav = page.locator('header nav:visible').first();
      await expect(desktopNav).toBeVisible();
      await expect(desktopNav.locator('a[href="/collections/the-hobbit"]:visible').first()).toBeVisible();
      await expect(desktopNav.locator('a[href="/collections/marvel-super-heroes"]:visible').first()).toBeVisible();
      await expect(desktopNav.locator('a[href="/collections/secrets-of-strixhaven"]:visible').first()).toBeVisible();
    }
  });

  test('collection renders product cards that link to products', async ({ page }) => {
    await gotoStorefront(page, '/collections/the-hobbit');
    await expect(page.locator('a[href*="/products/"]').first()).toBeVisible();
    expect(await page.locator('a[href*="/products/"]').count()).toBeGreaterThan(0);
  });

  test('search returns products for a real catalog term', async ({ page }) => {
    await gotoStorefront(page, '/search');
    const input = page.locator('#Search-In-Template');
    await expect(input).toBeVisible();
    await input.fill(searchTerm);
    await input.press('Enter');
    await expect(page).toHaveURL(url => url.pathname === '/search' && url.searchParams.get('q') === searchTerm);
    await expect(page.locator('.template-search h1')).toBeVisible();
    await expect(page.locator('.template-search a[href*="/products/"]').first()).toBeVisible();
  });

  test('search has a valid empty-result state', async ({ page }) => {
    const impossibleTerm = `e2e-no-result-${Date.now()}`;
    await gotoStorefront(page, `/search?q=${encodeURIComponent(impossibleTerm)}`);
    await expect(page.locator('.template-search h1')).toBeVisible();
    await expect(page.locator('.template-search .product-grid')).toHaveCount(0);
  });

  test('unknown routes remain healthy and expose the 404 template when the platform serves it', async ({ page }) => {
    const response = await gotoStorefront(page, `/e2e-missing-${Date.now()}`);
    await expectBasicPageHealth(page);

    const notFoundTemplate = page.locator('.template-404');
    if (response.status() === 404 || await notFoundTemplate.count()) {
      await expect(notFoundTemplate).toBeVisible();
      await expect(page.locator('.template-404 #Search-In-Template')).toBeVisible();
    } else {
      expect(response.status(), 'EasyStore may route unknown paths to the storefront shell').toBeLessThan(400);
      await expect(page.locator('.header__heading-link').first()).toBeVisible();
    }
  });
});

test.describe('product, cart, and checkout handoff', () => {
  test('product page exposes variant, quantity, add-to-cart, buy-now, and image modal behavior', async ({ page }) => {
    await gotoStorefront(page, limitedProductPath);
    await expect(page.locator('.product__title').first()).toBeVisible();
    await expect(page.locator('form[action="/cart/add"]').first()).toBeVisible();
    await expect(page.locator('select[name="id"]').first()).toHaveCount(1);
    await expect(page.locator('.quantity__input[name="quantity"]').first()).toHaveValue('1');
    await expect(page.locator('#AddToCart').first()).toBeVisible();
    await expect(page.locator('[data-buy-now]').first()).toBeVisible();

    const imageButton = page.locator('.js-image-modal-toggle').first();
    if (await imageButton.count()) {
      await imageButton.click();
      await expect(page.locator('#product-modal')).toHaveClass(/show/);
      await page.keyboard.press('Escape');
      await expect(page.locator('#product-modal')).toHaveClass(/hide/);
    }
  });

  test('limited products send signed-out add-to-cart attempts to login with a return target', async ({ page }) => {
    await gotoStorefront(page, limitedProductPath);
    const handle = new URL(page.url()).pathname.match(/\/products\/([^/?#]+)/)?.[1] || '';
    expect(await page.evaluate(productHandle => Boolean(window.CustomerOrderLimits?.ruleFor?.(productHandle)), handle)).toBe(true);
    const add = page.locator('#AddToCart').first();
    await expect(add).toHaveCount(1);

    // The limited product is a real catalog product, so it can sell out, and a
    // sold-out fixture is not a theme regression. EasyStore renders Add to Cart
    // disabled when the variant is unavailable, while the limit feature never
    // disables that button for a guest — it sends the shopper to sign in — and
    // stamps every control it does disable. A button disabled without that
    // marker is therefore out of stock, and the redirect below cannot be
    // exercised until it is restocked. The rule assertion above still runs, so
    // the limit itself stays covered; a button disabled *by the limit feature*
    // is still a failure, because a guest must never be blocked that way.
    const soldOut = await add.evaluate(button => (
      button.disabled && button.dataset.customerOrderLimitDisabled !== 'true'
    ));
    test.skip(soldOut, `${limitedProductPath} is sold out, so the signed-out add-to-cart redirect cannot be exercised`);

    await expect(add).toBeEnabled();
    await add.click();
    await page.waitForURL(url => url.pathname.includes('/account/login'));
    expect(page.url()).toContain('redirect');
  });

  test('an unlimited product can be added and removed through storefront cart actions', async ({ page }) => {
    await openConfiguredUnlimitedProduct(page);
    const addedCart = await addCurrentProductToCart(page);
    expect(addedCart.item_count).toBe(1);
    expect(addedCart.items?.length || 0).toBe(1);

    await removeFirstCartItem(page);
    const emptyCart = await readCart(page);
    expect(emptyCart.item_count).toBe(0);
    expect(emptyCart.items || []).toHaveLength(0);
  });

  test('cart checkout button hands the shopper to checkout or authentication', async ({ page }) => {
    await openConfiguredUnlimitedProduct(page);
    await addCurrentProductToCart(page);
    await gotoStorefront(page, '/cart');

    const checkout = page.locator('#checkout').first();
    await expect(checkout).toHaveCount(1);
    await checkout.evaluate(button => {
      const form = button.closest('form');
      if (!form) throw new Error('Checkout button is not inside a form');
      form.requestSubmit(button);
    });

    await page.waitForURL(url => url.pathname.includes('/checkout') || url.pathname.includes('/account/login'));
    expect(new URL(page.url()).pathname).toMatch(/\/(checkout|account\/login)/);
  });
});

test.describe('customer entry points', () => {
  test('account login entry offers a usable authentication flow', async ({ page }) => {
    await gotoStorefront(page, '/account/login');
    await expect(page).toHaveURL(/\/account\/login/);

    const classicEmail = page.locator('#CustomerEmail');
    if (await classicEmail.count()) {
      await expect(page.locator('#form-login')).toBeVisible();
      await expect(classicEmail).toHaveAttribute('required', '');
      await expect(page.locator('#CustomerPassword')).toHaveAttribute('required', '');
      await expect(page.locator('#form-login button[type="submit"]')).toBeVisible();
      await expect(page.locator('a[href="#recover"]')).toBeVisible();
      return;
    }

    const phoneInput = page.getByRole('textbox', { name: /mobile number/i });
    await expect(phoneInput).toBeVisible();
    await expect(page.getByRole('button', { name: /continue/i })).toBeVisible();
  });
});

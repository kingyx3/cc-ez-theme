# EasyStore browser E2E tests

These Playwright tests exercise a deployed EasyStore storefront rather than rendering Liquid locally. Every pull request runs the complete browser/device and Axe matrix. By default PRs target `https://cardboard.sg`; set the repository Actions variable `E2E_PR_BASE_URL` when a deployed preview storefront is available so the same suite validates that preview instead.

## Run locally

```bash
npm install
npx playwright install chromium firefox webkit
npm run test:e2e
```

Override runtime data without changing test code:

```bash
E2E_BASE_URL=https://preview.example.com \
E2E_LIMITED_PRODUCT_PATH=/products/pin-a-specific-limited-product \
E2E_UNLIMITED_PRODUCT_PATH=/products/known-unlimited-product \
E2E_SEARCH_TERM=Hobbit \
npm run test:e2e
```

`E2E_LIMITED_PRODUCT_PATH` is optional. Left unset, the suite reads the handles configured in `theme/snippets/customer-order-limit-config.liquid` and opens the first one the storefront publishes a purchase-limit rule for, falling back to the collections that carry limited products if a handle does not resolve as a bare `/products/<handle>` URL. So a product whose SKU changes — or a limit that moves to a different product — needs no change here. Set the variable only to pin one specific product.

## GitHub Actions

Every pull request runs all of the following:

- Playwright suite/configuration validation
- storefront reachability preflight
- Chromium desktop
- Firefox desktop
- WebKit desktop
- Pixel 7 / mobile Chrome emulation
- iPhone 15 / mobile Safari emulation
- Axe serious/critical accessibility checks

The PR target resolves in this order: `E2E_PR_BASE_URL`, `E2E_BASE_URL`, then `https://cardboard.sg`. The workflow can also be run manually with an explicit `base_url`.

The suite covers storefront shell/navigation, responsive menus, collections, positive and empty search, unknown-route/404 behavior, PDP controls and image modal, guest purchase-limit login redirect, cart add/update/remove state, checkout handoff, login UI, uncaught same-origin JavaScript errors, broken same-origin resources, horizontal overflow, cross-browser/device projects, and automated Axe checks.

Known EasyStore/platform behavior is narrowly baselined instead of disabling checks wholesale: third-party script exceptions are ignored, the injected cart-view `getCart` null error is recorded as a known platform error, and existing accessibility findings are allowlisted by exact Axe rule and DOM target. Any new same-origin error, broken resource, or serious/critical accessibility target still fails CI.

The checkout test stops after EasyStore takes control of checkout/authentication and never places an order. Cart mutations live only in the isolated browser session.

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
E2E_LIMITED_PRODUCT_PATH=/products/known-limited-product \
E2E_UNLIMITED_PRODUCT_PATH=/products/known-unlimited-product \
E2E_SEARCH_TERM=Hobbit \
npm run test:e2e
```

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

## When the limited fixture product sells out

`E2E_LIMITED_PRODUCT_PATH` names a real catalog product, so its stock changes without anyone touching this repository. The guest purchase-limit redirect test still asserts that the storefront publishes a limit rule for that product, but it **skips** the add-to-cart leg when EasyStore renders Add to Cart disabled for an unavailable variant — an out-of-stock catalog product is not a theme regression, and the button cannot be clicked. The run reports the test as skipped rather than passing silently; point `E2E_LIMITED_PRODUCT_PATH` at a limited product that is in stock to restore full coverage.

The skip is deliberately narrow. The limit feature never disables Add to Cart for a signed-out shopper — it sends them to `/account/login` — and it stamps `data-customer-order-limit-disabled="true"` on every control it does disable, so a button disabled by the limit feature still fails the test.

Known EasyStore/platform behavior is narrowly baselined instead of disabling checks wholesale: third-party script exceptions are ignored, the injected cart-view `getCart` null error is recorded as a known platform error, and existing accessibility findings are allowlisted by exact Axe rule and DOM target. Any new same-origin error, broken resource, or serious/critical accessibility target still fails CI.

The checkout test stops after EasyStore takes control of checkout/authentication and never places an order. Cart mutations live only in the isolated browser session.

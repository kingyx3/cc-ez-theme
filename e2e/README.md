# EasyStore browser E2E tests

These Playwright tests exercise the published EasyStore storefront rather than rendering Liquid locally.

## Run locally

```bash
npm install
npx playwright install chromium firefox webkit
npm run test:e2e
```

Defaults target `https://cardboard.sg`. Override runtime data without changing test code:

```bash
E2E_BASE_URL=https://preview.example.com \
E2E_LIMITED_PRODUCT_PATH=/products/known-limited-product \
E2E_UNLIMITED_PRODUCT_PATH=/products/known-unlimited-product \
E2E_SEARCH_TERM=Hobbit \
npm run test:e2e
```

The suite covers storefront shell/navigation, responsive menus, collections, positive and empty search, 404, PDP controls and image modal, guest purchase-limit login redirect, add/update/remove cart behavior, checkout handoff, login UI, uncaught JavaScript errors, broken same-origin resources, horizontal overflow, cross-browser/device projects, and automated Axe checks.

The checkout test stops after EasyStore takes control of checkout/authentication and never places an order. Cart mutations live only in the isolated browser session.

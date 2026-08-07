# EasyStore browser E2E tests

These Playwright tests exercise a deployed EasyStore storefront rather than rendering Liquid locally. Because pull-request theme changes are not automatically deployed to `cardboard.sg`, PR CI validates that the Playwright suite compiles and only runs the full browser matrix when a preview storefront URL is explicitly configured.

## Run locally

```bash
npm install
npx playwright install chromium firefox webkit
npm run test:e2e
```

Defaults for local/manual runs can target `https://cardboard.sg`. Override runtime data without changing test code:

```bash
E2E_BASE_URL=https://preview.example.com \
E2E_LIMITED_PRODUCT_PATH=/products/known-limited-product \
E2E_UNLIMITED_PRODUCT_PATH=/products/known-unlimited-product \
E2E_SEARCH_TERM=Hobbit \
npm run test:e2e
```

## GitHub Actions

Every pull request runs `npx playwright test --list` so syntax, configuration, imports, and the complete project/test matrix are validated without requiring a deployed theme build.

To run the full functional and Axe suites on pull requests, set the repository Actions variable `E2E_PR_BASE_URL` to a deployed EasyStore preview URL. The browser jobs stay skipped when that variable is empty, because testing an undeployed PR branch against the published production theme cannot validate the branch's changes.

You can also run the **EasyStore browser E2E** workflow manually and provide a `base_url`; the manual default is `https://cardboard.sg`.

The suite covers storefront shell/navigation, responsive menus, collections, positive and empty search, 404, PDP controls and image modal, guest purchase-limit login redirect, add/update/remove cart behavior, checkout handoff, login UI, uncaught same-origin JavaScript errors, broken same-origin resources, horizontal overflow, cross-browser/device projects, and automated Axe checks. Third-party script exceptions are not treated as theme failures.

The checkout test stops after EasyStore takes control of checkout/authentication and never places an order. Cart mutations live only in the isolated browser session.

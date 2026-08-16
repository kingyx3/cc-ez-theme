# Theme production safety checklist

Use this checklist for changes affecting shared product cards, product forms, cart behavior, checkout entry points, global assets, or the generated EasyStore package.

## Required design invariants

- Optional features must be true no-ops when disabled: no asset load, global state reset, event replacement, or API replacement.
- Do not replace `EasyStore.Action` methods or custom-element prototypes to enforce business rules.
- Never manufacture partial objects for native callbacks.
- Keep network calls and response handling in the native component that already owns them.
- Do not implement cross-order or checkout authorization solely in theme JavaScript. Use an EasyStore server-side capability or backend/app validation.
- Failed requests must restore editable UI state and must not consume local allowance.
- Cart decreases and removals must remain available as recovery paths.
- Preserve Liquid variables, translated labels, app hooks, data attributes, and native response handling unless removal is explicitly required.
- Critical visibility behavior belongs at the markup source or in an asset guaranteed to load on every affected surface.
- Storefront and theme-editor asset mirrors must remain identical.

## EasyStore package invariant

The upload ZIP must contain exactly one theme wrapper directory:

```text
cc-ez-theme/
├── assets/
├── config/
├── editor_assets/
├── editor_config/
├── layout/
├── sections/
├── snippets/
└── templates/
```

Do not flatten the required wrapper. Do not add an outer repository directory or a nested ZIP. Download the GitHub artifact and upload it without extracting or recompressing it.

## Required review matrix

Review all of these paths for shared commerce changes:

- homepage, featured, collection, search, recommendation, and cart-recommendation cards;
- main product, featured product, and quick-view forms;
- product properties/customization flows;
- add-to-cart success, explicit rejection, malformed response, and concurrent interaction;
- cart increase, decrease, removal, promotion refresh, and empty-cart transition;
- Buy Now and checkout submission;
- logged-out and logged-in customers;
- sale, sold-out, unavailable, zero-price, and multi-variant products;
- desktop and mobile.

## Required validation

1. Compare the proposed runtime to the last known-good production commit, not only to current `main`.
2. Run the real-theme validator.
3. Run the complete test suite with line and branch coverage enforcement.
4. Build the downloadable ZIP.
5. Extract and revalidate the packaged theme while preserving the required wrapper contract.
6. Inspect packaged files for the exact production behavior, not only repository source.
7. Upload the unmodified artifact to an unpublished EasyStore preview theme.
8. Test realistic customer data and installed app snippets.
9. Record a rollback that restores the last known-good storefront behavior without retaining experimental hooks.

Every step above happens before the change reaches `main`. A successful workflow run on `main` imports the theme into EasyStore and publishes it, so the merge itself is the release. There is no post-merge window in which to preview.

Static validation proves syntax and repository contracts. It cannot prove live asset ordering, account data, app integration, platform responses, or storefront rendering. A production preview is mandatory for shared commerce changes.

## PR #56 incident rule

The custom across-order purchase-limit implementation introduced in PR #56 was removed after repeated live failures. Do not restore its global loader, runtime files, API interception, prototype changes, synthetic responses, capture-phase guards, or native-component integrations. Any future cross-order limit must begin with server-side enforcement and a new architecture review.

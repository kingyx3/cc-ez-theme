# Theme production safety checklist

Use this checklist for changes affecting shared product cards, product forms, cart behavior, checkout entry points, or global theme assets.

## Required design invariants

- Optional features must be true no-ops when disabled: no asset load, global state reset, event replacement, or API replacement.
- Do not replace `EasyStore.Action` methods or custom-element prototypes to enforce business rules.
- Never manufacture partial objects for native callbacks.
- Keep network calls and response handling in the native component that already owns them.
- Update local business state only after a confirmed successful callback or from server-rendered response HTML. Do not infer success from unrelated counters, timers, or concurrent UI mutations.
- Failed requests must restore editable UI state and must not consume local allowance.
- Cart decreases and removals must remain available as recovery paths.
- Preserve Liquid variables, translated labels, app hooks, data attributes, and native response handling unless removal is explicitly required.
- Critical visibility behavior belongs at the markup source or in an asset guaranteed to load on every affected surface.
- Storefront and theme-editor asset mirrors must remain identical.

## Required review matrix

Review all of these paths for shared commerce changes:

- homepage, featured, collection, search, recommendation, and cart-recommendation cards;
- main product, featured product, and quick-view forms;
- product properties/customization flows;
- add-to-cart success, explicit rejection, malformed/incomplete response, and concurrent interaction;
- cart increase, decrease, removal, promotion refresh, and empty-cart transition;
- Buy Now and checkout submission;
- logged-out and logged-in customers;
- sale, sold-out, unavailable, zero-price, and multi-variant products;
- desktop and mobile.

## Required validation

1. Run the real-theme validator.
2. Run the complete test suite with line and branch coverage enforcement.
3. Build the downloadable ZIP.
4. Extract and revalidate the packaged theme.
5. Inspect packaged files for the exact production behavior, not only repository source.
6. Upload the artifact to an EasyStore preview theme.
7. Test realistic customer order data and installed app snippets.
8. Record a feature-level rollback that does not require reverting unrelated work.

Static validation proves syntax and repository contracts. It cannot prove live asset ordering, CDN behavior, account data, app integration, or platform response variations. A production preview is mandatory for shared commerce changes.

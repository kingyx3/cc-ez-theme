# Theme production safety checklist

Use this checklist for changes that affect shared product cards, product forms, cart behavior, checkout entry points, or global theme assets.

## Required design invariants

- Optional features must be true no-ops when disabled: no asset load, no global state reset, and no event/API replacement.
- Do not replace `EasyStore.Action` methods or custom-element prototypes to enforce business rules.
- Never return synthetic partial objects to native cart callbacks.
- Preserve existing Liquid variables, translated labels, app hooks, data attributes, and native response handling unless removal is explicitly required.
- Critical visibility rules belong at the markup source or in an asset guaranteed to load on every affected surface—not in a stylesheet owned by an unrelated optional feature.
- Storefront and theme-editor asset mirrors must remain identical.

## Required review matrix

For shared commerce changes, review all of these paths:

- homepage/featured product cards;
- collection and search listings;
- recommendations and cart recommendations;
- main product form;
- featured product and quick view;
- cart quantity increase, decrease, removal, and empty-cart transition;
- Buy Now and checkout submission;
- logged-out and logged-in customers;
- sale, sold-out, unavailable, zero-price, and property/customization products;
- desktop and mobile.

## Required validation

1. Run the real-theme validator.
2. Run the complete unit suite with line and branch coverage enforcement.
3. Build the downloadable ZIP.
4. Extract and revalidate the packaged theme.
5. Inspect the packaged files for the exact production behavior, not only repository source.
6. Preview live EasyStore rendering with realistic products and app snippets.
7. Record a feature-level rollback that can be executed without reverting unrelated work.

Static validation proves syntax and repository contracts. It does not prove live asset ordering, CDN behavior, app integration, server response shapes, or storefront rendering. A production preview is mandatory for shared commerce changes.
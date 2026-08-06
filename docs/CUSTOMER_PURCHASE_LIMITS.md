# Customer purchase limits rollback

The custom across-order customer purchase-limit feature introduced in PR #56 has been removed from the theme.

## Why it was removed

The feature changed global storefront behavior by loading on every page and intercepting product and cart flows. Later attempts to narrow the integration still required changes across shared product-form, listing, cart, and checkout code. The live EasyStore theme continued to fail even when static validation, tests, and packaging succeeded.

The production-safe decision is to restore the exact pre-PR #56 storefront behavior rather than continue layering compatibility fixes onto shared commerce paths.

## Current behavior

- The theme no longer loads `customer-purchase-limits.js`.
- The theme no longer includes `customer-purchase-limits.liquid`.
- Product forms, quick add, cart updates, removals, promotions, and checkout use their existing EasyStore-native behavior.
- Existing inventory, store, promotion, and contextual purchase-limit feedback remain unchanged.
- The EasyStore upload archive still requires the single `cc-ez-theme/` wrapper directory. Packaging was not the cause of this incident and must not be flattened.

## Reintroduction requirements

Do not reintroduce cross-order customer limits as a theme-level JavaScript feature.

A future implementation must meet all of these requirements before theme work begins:

1. Enforcement is provided by an EasyStore server-side feature or a backend/app checkout validator.
2. Direct API requests and non-theme sales channels cannot bypass the limit.
3. The storefront integration is display-only or consumes an official server response; it must not replace EasyStore APIs, custom-element prototypes, or native callback payloads.
4. The feature can be disabled without loading assets or changing any product/cart behavior.
5. A real unpublished EasyStore theme is tested with installed apps, realistic accounts, prior orders, rejected requests, multiple variants, desktop, and mobile.
6. The generated GitHub artifact is uploaded without extracting or recompressing and retains the required `cc-ez-theme/` wrapper.

## Rollback verification

The regression suite verifies that all PR #56 runtime files and identifiers are absent, that `currencies.liquid` uses the pre-PR #56 loading path, and that shared commerce files no longer contain the custom across-order integration.

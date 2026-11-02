# Customer purchase limits: current state and historical rollback

## Current implementation (main)

The active storefront uses `theme/snippets/customer-order-limits.liquid`, `customer-order-limit-config.liquid`, `customer-order-limit-row.liquid`, and `theme/assets/customer-order-limits.js`. The module is included conditionally from `theme/snippets/currencies.liquid` on purchase-capable pages. Limits are configured per product handle/SKU and can account for previous orders and cart quantities when the history loader succeeds.

Refer to [CUSTOMER_ORDER_LIMITS.md](CUSTOMER_ORDER_LIMITS.md) for operational configuration and diagnostics. **The actual configuration file, not the examples in documentation, is the source of truth for current handles and maxima.**

## Historical rollback

PR #56's earlier `customer-purchase-limits.js` / `customer-purchase-limits.liquid` implementation was rolled back after live EasyStore failures. Those **old filenames** are absent; that rollback does **not** mean the newer `customer-order-limits.js` implementation is absent. Earlier wording on this page incorrectly described the current storefront as entirely native.

Do not revive the removed global interception implementation or assume static tests prove live EasyStore compatibility.

## Enforcement boundary and release requirements

The active implementation is a **theme-level safeguard**, not authoritative checkout authorization. Browser modifications, disabled JavaScript, direct APIs, concurrent tabs and other sales channels can bypass it. Hard limits require EasyStore server-side support or a backend checkout validator.

Any extension should preserve native purchase flows, be optional per product, keep the ability to disable rules by configuration, and undergo automated tests plus real unpublished-theme testing with installed apps, logged-in/guest shoppers, previous orders, cart, Buy Now, quick add, and mobile. Preserve the required `cc-ez-theme/` wrapper in deployment archives.

## Related documentation

- [CUSTOMER_ORDER_LIMITS.md](CUSTOMER_ORDER_LIMITS.md) — current rule behavior, refresh windows, history loading, testing and operational guidance.

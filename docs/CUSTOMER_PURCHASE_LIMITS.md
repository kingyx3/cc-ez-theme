# Customer purchase limits across orders

The theme can provide customer-facing purchase-limit guidance for selected EasyStore products by reading a signed-in customer's order history. This is a storefront safeguard, not server-side authorization.

## Production architecture

The implementation follows four safety rules:

1. **Disabled means no runtime change.** When `customer_purchase_limit_rules` is blank, the snippet emits no configuration and loads no purchase-limit JavaScript.
2. **No global monkey patching.** The feature does not replace `EasyStore.Action` methods and does not modify custom-element prototypes.
3. **Checks run at theme-owned interaction boundaries.** Capture-phase guards cover listing quick-add, product-form add-to-cart, Buy Now, cart quantity changes, and cart checkout.
4. **Native responses remain native.** The guard never manufactures partial cart responses, so cart HTML, counts, promotions, loading states, and error handling remain under the existing theme components.

This architecture replaced the original PR #56 implementation, which loaded globally even with blank configuration and wrapped EasyStore/cart APIs on every storefront page.

## Configure limits

Edit `theme/snippets/customer-purchase-limits.liquid` and set `customer_purchase_limit_rules`:

```liquid
{% assign customer_purchase_limit_rules = 'limited-coffee|2|2026-09-01,2027-01-01;members-box|1|2026-12-01' %}
```

Each semicolon-separated rule uses:

```text
product-handle|maximum-units|comma-separated-refresh-dates
```

The refresh-date field is optional:

```liquid
{% assign customer_purchase_limit_rules = 'one-time-box|1|' %}
```

The parser intentionally processes at most 20 product rules and 20 refresh dates per rule. Keep the configuration small because signed-in storefront rendering reads the customer's relevant order history for each configured product.

## Refresh dates

The latest refresh date that has already passed becomes the start of the current entitlement period. Orders before that date no longer count.

Refresh dates are used only by Liquid. They are not serialized into browser configuration and are not shown in customer-facing messages.

## Counting behavior

- Quantities across all variants of the same product handle are combined.
- Non-cancelled customer orders count.
- Cancelled orders do not count.
- Refunded orders still count unless EasyStore also marks the order cancelled.
- Current cart quantities consume the remaining allowance.
- A configured limited product requires a signed-in customer.
- Customers may always reduce or remove cart quantities, including when they are logged out or the cart is already above the current allowance.

## Supported theme surfaces

The guard covers the theme's shared product cards, main product form, featured product form, product quick view, cart quantity controls, and cart checkout form. Liquid renders a variant-to-product-handle map only for configured products, while listing buttons use their existing product-handle data. The browser does not fetch product records.

## Production rollout checklist

1. Leave the configuration blank while deploying the code change and confirm the storefront behaves identically to the prior theme.
2. Configure one staging/test product handle with a low limit.
3. Test logged-out quick add, product add, and Buy Now.
4. Test a signed-in customer with zero prior purchases, some prior purchases, and a fully consumed allowance.
5. Test multiple variants of the same product and multiple cart lines for the same handle.
6. Test cart increases, decreases, removals, and checkout.
7. Test one sale product and one sold-out product to catch shared product-card regressions.
8. Run the repository workflow, download the generated ZIP, and inspect the packaged files.
9. Publish to a preview theme first and smoke-test desktop and mobile before promoting it to production.

## Monitoring and rollback

If storefront errors appear, immediately blank `customer_purchase_limit_rules`. The next rendered page will emit no purchase-limit runtime code. This is the fastest feature-level rollback and does not require reverting unrelated theme changes.

For a full rollback, revert the production-readiness PR. Do not restore the original global API/prototype wrappers.

## Enforcement boundary

A customer can bypass theme JavaScript with a direct API request, modified client, custom sales channel, or disabled browser scripting. Hard enforcement requires an EasyStore server-side feature or a custom backend/app validation at checkout.
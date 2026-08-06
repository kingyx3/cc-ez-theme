# Customer purchase limits across orders

The theme can provide customer-facing purchase-limit guidance for selected EasyStore products by reading a signed-in customer's order history. This remains a storefront safeguard, not server-side authorization.

## Production architecture

The final implementation is deliberately narrow:

1. **Disabled means no runtime change.** When `customer_purchase_limit_rules` is blank, the snippet emits no configuration and loads no purchase-limit JavaScript.
2. **The runtime is a pure helper.** It does not replace `EasyStore.Action` methods, custom-element prototypes, or native callback responses.
3. **Theme-owned components call the helper directly.** Existing product-form, listing quick-add, cart-update, removal, and checkout paths perform the checks before their native action.
4. **State changes follow confirmed native outcomes.** Successful add callbacks record the confirmed request. Cart updates and removals resync from EasyStore's rendered cart HTML; rejected requests do not consume allowance.
5. **Cart recovery is always possible.** Customers may reduce or remove quantities even when logged out or already above the current allowance.

This replaces the original PR #56 architecture, which loaded globally with blank configuration, wrapped EasyStore APIs, modified the product-form prototype, and returned synthetic partial cart responses.

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

The parser processes at most 20 product rules and 20 refresh dates per rule. Keep the configuration small because signed-in storefront rendering reads relevant order history for each configured product.

## Refresh dates

The latest refresh date that has already passed becomes the start of the current entitlement period. Orders before that date no longer count.

Refresh dates are used only by Liquid. They are not serialized into browser configuration and are not shown in customer-facing messages.

## Counting behavior

- Quantities across every variant and cart line of the same product handle are combined.
- Non-cancelled customer orders count.
- Cancelled orders do not count.
- Refunded orders still count unless EasyStore also marks the order cancelled.
- Current cart quantities consume the remaining allowance.
- A configured limited product requires a signed-in customer.
- Successful additions update the in-page allowance only after EasyStore confirms the add.
- Cart updates resync from EasyStore's returned `cart_content` when available.
- Rejected cart updates restore the edited line's previous quantity.

## Supported theme surfaces

The guard covers shared product cards, the main product form, featured product forms, product quick view, cart quantity controls, cart removal, and cart checkout. Liquid renders a variant-to-handle map only for configured products. Cart forms include the product handle for each line, so multi-variant and multi-line totals do not depend on a browser product lookup.

## Production rollout checklist

1. Deploy the code with the configuration blank and confirm all product and cart behavior is unchanged.
2. Enable one staging product with a low limit.
3. Test logged-out quick add, product add, Buy Now, cart increase, cart decrease, removal, and checkout.
4. Test signed-in customers with zero prior purchases, partial usage, and a fully consumed allowance.
5. Test multiple variants and multiple cart lines of the same product.
6. Test an EasyStore-rejected add and update; confirm the allowance and displayed cart quantity do not drift.
7. Test a sale product and sold-out product to cover the shared product card.
8. Download the CI artifact, upload it as an EasyStore preview theme, and smoke-test desktop and mobile.
9. Promote the preview only after the live account/order/app-snippet matrix passes.

## Monitoring and rollback

For immediate feature rollback, blank `customer_purchase_limit_rules`. The next rendered page emits no purchase-limit runtime code, without reverting unrelated theme changes.

For a full rollback, revert the production-readiness PR. Do not restore the original API wrappers, prototype modifications, synthetic callback responses, or cart-count inference.

## Enforcement boundary

A direct API request, modified client, disabled JavaScript, custom sales channel, or other storefront can bypass theme code. Hard enforcement requires an EasyStore server-side purchase-limit capability or custom backend/app validation at checkout.

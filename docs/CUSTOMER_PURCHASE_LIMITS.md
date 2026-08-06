# Customer purchase limits across orders

The theme can apply a per-customer entitlement to selected EasyStore products by reading the signed-in customer's order history.

## Configure limits

Edit:

`theme/snippets/customer-purchase-limits.liquid`

Set `customer_purchase_limit_rules` with one or more semicolon-separated rules:

```liquid
{% assign customer_purchase_limit_rules = 'limited-coffee|2|2026-09-01,2027-01-01;members-box|1|2026-12-01' %}
```

Each rule uses:

```text
product-handle|maximum-units|comma-separated-refresh-dates
```

The refresh-date field is optional:

```liquid
{% assign customer_purchase_limit_rules = 'one-time-box|1|' %}
```

## How refresh dates work

For each product, the latest refresh date that has already passed becomes the start of the current entitlement period. Orders before that date no longer count. The next future refresh date is shown in purchase-limit feedback.

Example:

```text
limited-coffee|2|2026-09-01,2027-01-01
```

- Before September 1, 2026, all non-cancelled orders count.
- From September 1, 2026, only orders on or after September 1 count.
- From January 1, 2027, only orders on or after January 1 count.

Add another future date whenever the entitlement should refresh again.

## Counting behavior

- Limits are product-level, so quantities across all variants of the same product handle are combined.
- Quantities are combined across the customer's non-cancelled orders.
- Cancelled orders do not count.
- Refunded orders still count unless the order is also marked cancelled.
- Current cart quantities also consume the remaining entitlement.
- A customer must sign in before adding a configured limited product.

## Theme enforcement boundary

This is a storefront guard implemented in Liquid and JavaScript. It covers the theme's product forms, quick add flows, cart updates, and cart checkout submission. It is not a server-side authorization rule: a custom client, direct API request, another sales channel, or modified storefront code can bypass theme JavaScript.

Use an EasyStore server-side purchase-limit feature or a custom app/backend validation for hard enforcement at checkout. The theme guard remains useful for immediate customer feedback and normal storefront use.

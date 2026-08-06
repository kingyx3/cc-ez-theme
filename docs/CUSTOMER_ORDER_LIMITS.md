# Customer order limits

This feature limits a signed-in customer to a configured number of units for an EasyStore product handle across non-cancelled orders and the current cart.

## Configured limits

| EasyStore product handle | Per-customer maximum |
| --- | ---: |
| `MTG-HOB-BDL-EN` | 2 |
| `MTG-HOB-CBB-EN` | 2 |
| `MTG-HOB-CBB-EN-CASE6` | 1 |
| `MTG-HOB-CBB-EN-PACK` | 2 |
| `MTG-HOB-DNK-EN` | 3 |
| `MTG-HOB-PBB-EN` | 12 |
| `MTG-HOB-PRK-EN-SET4` | 1 |
| `MTG-HOB-OBP-EN` | 1 |
| `MTG-HOB-SCN-EN-SET2` | 1 |
| `CC-BDL-SCENES3-EN` | 1 |
| `CC-BDL-FRIENDS3-EN-SPM` | 1 |
| `CC-BDL-FRIENDS3-EN-MSH` | 1 |
| `CC-BDL-SPIDERVAULT-EN` | 1 |
| `CC-BDL-UNEXPECTED-EN` | 2 |

Rows supplied with a blank promo maximum are intentionally not configured and remain unlimited. This includes `MTG-HOB-GFB-EN`, the listed `MTG-MSH-*`, `MTG-SOS-*`, and `MTG-SPM-*` handles, plus `CC-BDL-HAPPYHAMPER-EN` and `CC-BDL-HAPPYHAMPER-EN-PBB`.

The values remain explicit in `theme/snippets/customer-order-limit-config.liquid`. Every configured and storefront handle is normalized to lowercase before comparison because EasyStore product URLs use lowercase handles even when administrative values are capitalized.

## Renewing an allowance

Each slot has a `customer_order_limit_refresh_N` timestamp, and `customer_order_limit_refresh_all` covers every slot that leaves its own blank. Once a refresh timestamp has passed, orders placed before it stop counting, so every customer starts that limit again from zero. A timestamp in the future changes nothing until it arrives, and a blank one keeps counting every past order forever.

Write timestamps with the store's timezone offset:

```liquid
{% assign customer_order_limit_refresh_10 = '2026-09-01 00:00:00 +0800' %}
```

Renewal is evaluated when the page renders, so it takes effect on the next page load after the timestamp passes. Storefront copy names the date once a window is active — "The limit is 1 unit per customer across orders since Sep 01, 2026" — and each rule publishes `refreshAt` and `limitWindowLabel` so the configuration can be verified in the browser console.

To renew a limit, set the timestamp rather than clearing the maximum: clearing the maximum disables the slot entirely, while a refresh keeps the limit enforced for purchases made from that date onwards.

## Enforcement

Liquid makes one pass through the customer's orders and one pass through `cart.items`, combining quantities for every line with the same normalized identifier. Cancelled orders are ignored, and orders older than the slot's refresh window are skipped.

A line is matched on **either** its product handle **or** its SKU. A configured value such as `MTG-HOB-SCN-EN-SET2` is both the storefront handle and the SKU, and order line items do not expose the same identifier on every store — matching only `product.handle` counted zero units, which let a customer reorder the same product in order after order. Blank identifiers are replaced with sentinels so an unconfigured slot can never match a line that simply has no handle or no SKU. Quantities and the order and line collections each read a fallback field name for the same reason.

`window.customerOrderLimitsV2.diagnostics` reports what the history pass could actually read: `ordersSeen`, `lineItemsSeen`, and an `identifiers` sample in `handle/sku×quantity` form. `ordersSeen: 0` for a signed-in customer with orders means the storefront cannot see order history at all; a populated sample whose values never match a configured slot means the identifiers differ from what is configured.

## When a page cannot see order history

`customer.orders` carries line items on the account order pages — `templates/customers/orders.liquid` renders them — but a product or cart page can receive the orders list without them, or without orders at all. The inline pass then counts zero units and the limit quietly stops applying across orders, which is how a customer could reorder a limited product after paid and fulfilled orders.

So history is loaded when the page could not read it:

1. `templates/customers/orders.liquid` publishes every non-cancelled line item as JSON in `#customer-order-limit-history` — handle, SKU, order date, quantity, capped at 500 lines. It does no filtering; the reading page applies its own configured handles and refresh windows, so there is one matching implementation.
2. A page whose `diagnostics.lineItemsSeen` is `0` treats history as **unknown**, not as "nothing purchased", and fetches `/account/orders` in the background as the page loads. The result is cached in `sessionStorage` for five minutes per customer, so it costs one request per session.
3. `purchased` is recomputed from the payload, allowances and copy update, and `customer-order-limits:history` fires alongside the usual `cart-sync`.

A purchase attempted while history is still unknown is **held** rather than measured against an allowance that assumes nothing was bought: the shopper sees "Checking your purchase limit for this product. One moment, then try again." Because the load starts at page load, that window is normally too short to see.

Every failure path falls open to cart-only enforcement rather than blocking a sale: a failed or redirected request, a missing payload (an account template that was not updated), a browser without `fetch` or `DOMParser`, and a shopper proven to be signed out, who is never fetched for. `window.CustomerOrderLimits.historyState()` reports which case applies — `inline`, `loaded`, `pending`, `unknown`, or `unavailable`.

The shared validator integrates with the native theme paths:

- product page, featured product, and quick-view quantity validation;
- Add to Cart and Buy Now;
- listing quick-add;
- cart quantity updates;
- standard checkout, express checkout, and additional checkout controls.

Successful additions and cart updates change the browser-side allowance only after EasyStore's native callback confirms success. Rejected requests do not consume allowance. Cart decreases and removals remain available so an over-limit cart can be corrected.

Addition guards apply to add-to-cart forms only. The hidden Buy Now checkout form lives inside the same `<product-form>` element as the add form, so a guard matching every `product-form form` blocks checkout instead of an addition — that stranded Buy Now with a spinning button and a stale limit message. A form qualifies as an add-to-cart form only when it is not `[data-buy-now-checkout-form]` and it either contains a `[name="add"]` control or posts to `/cart/add`.

## Buy Now at the limit

Buy Now adds a unit and then goes to checkout, so on a product whose allowance is already in the cart there is nothing left to add. In that case — no allowance remaining and at least one unit of the product already in the cart — Buy Now skips the addition and goes straight to checkout with the current cart. It does not retry the add, and it does not open the limit modal.

The modal is for the cases where checkout with the current cart is not what the shopper asked for:

- the allowance is spent on previous orders and the product is not in the cart, so it cannot be bought at all;
- more units were requested than may still be added, so the message states how many remain.

`goToCheckout()` reports whether checkout actually started. Buy Now restores its buttons when it did not, and releases them after 8 seconds if navigation is blocked downstream, so a failed checkout can never leave a permanently spinning button.

Limit copy is generated from live quantities, not from the message rendered into the page by Liquid. The rendered copy is correct only for the cart as it was on page load, which is how a maxed-out product ended up saying "you can add up to 1 more".

## Signed-out shoppers

A limit counts units per customer across orders, so it can only be measured for a signed-in customer. Guests are therefore never measured against an allowance. Instead, a purchase attempt on a limited product sends the shopper to `/account/login?redirect_uri=<current page>`, where the login page also links to registration:

- Add to Cart, Buy Now, and listing quick-add on a limited product;
- cart checkout — standard, express, and additional controls — while a limited product is in the cart.

For a guest, no limit rule contributes a quantity maximum, disables a purchase or checkout control, clamps a cart quantity input, or replaces native purchase-limit copy. Once the customer signs in, the same rules apply with their real order history.

The redirect is scoped to the product being bought. A limited product sitting in the cart never diverts Add to Cart or Buy Now for a different product; only the cart's own checkout controls consider the whole cart.

## How sign-in state is decided

A wrong redirect breaks buying for real customers, so the storefront redirects only when the page proves the shopper is signed out. Three signals are read, in order:

1. `body.customer-logged-in` from `layout/theme.liquid`, `[data-customer-authenticated="true"]` from `sections/header.liquid`, or any `/account/logout` link — signed in;
2. `customerAuthenticated` from `snippets/customer-order-limits.liquid` — a signed-in hint only;
3. `[data-customer-authenticated="false"]` from `sections/header.liquid` — signed out.

Signals 1 and 2 are checked first and end the question. Being signed out is only ever concluded from the header's signed-out marker in signal 3, never from missing markup, and never on an `/account` path. If no signal resolves — for example when customer accounts are disabled and the header renders no account markup — the shopper is treated as not signed out: limits apply as usual and no purchase is redirected.

Signals 1 and 3 come from the layout and header, which render from the `{% if customer %}` check the whole theme uses for its account links. The Liquid flag in signal 2 only reports what the limit snippet itself could see, which is why it cannot mark a shopper as a guest. That snippet also gates the `customer.orders` pass, so if it under-reports sign-in state the across-order `purchased` counts fall back to `0` and only the current cart is capped. To verify on a live theme, sign in and check `window.customerOrderLimitsV2` in the console: `customerAuthenticated` must be `true` and `purchased` must reflect prior orders.

## Root cause corrected

The first deployed version compared uppercase configured handles with lowercase storefront handles, so no rule matched. It also relied mainly on document listeners and missed native Buy Now and cart paths. The corrected version normalizes both sides and validates inside the existing product, listing, and cart components, with delegated capture guards as defense in depth.

## Checking a live product page

The feature logs nothing, so an empty console is normal and not a symptom. Its state lives on `window.customerOrderLimitsV2` and `window.CustomerOrderLimits`.

Paste `scripts/limit-check.console.js` into the browser console on a product page that has a configured limit, signed in as a customer who has bought that product before. It prints sign-in state, what history the page could read, the numbers for that product, whether the account payload is reachable, and one of these verdicts:

| Verdict | Meaning |
| --- | --- |
| `WORKING` | past orders are counted for this product |
| `NO PURCHASES COUNTED` | the customer has not bought it, or the identifiers do not match the configured handle — compare `identifiers` and `payload lines` in the output |
| `BROKEN` | history could not be read or loaded; only the current cart is capped |
| `NOT LIMITED` | no rule for this handle |
| `GUEST` | not signed in, so limits do not apply and purchase clicks go to login |
| `older build is published` | the uploaded theme predates the diagnostics field |

Without the console: buy one unit of a product whose limit is 1, complete the order, then reload its product page. Add to Cart should be disabled with "Maximum quantity reached", and Buy Now should go straight to checkout rather than adding a second unit.

## Preview validation

Before merging or publishing, upload the exact workflow ZIP to an unpublished EasyStore theme and verify:

1. each configured handle permits its maximum but blocks one additional unit;
2. prior non-cancelled order quantities reduce the remaining allowance;
3. multiple variants and cart lines for one handle are combined;
4. Add to Cart, Buy Now, listing quick-add, cart increases, standard checkout, and express checkout are blocked when over limit;
5. cart decreases and removals continue to work;
6. rejected requests do not reduce the remaining allowance;
7. signed out, Add to Cart, Buy Now, listing quick-add, and cart checkout on a limited product open the login page and return to the original page after signing in, with no limit message, disabled control, or clamped quantity shown first;
8. signed in, every purchase path works normally on desktop and mobile and never reaches an account page — check a limited product, an unlimited product, and an unlimited product bought while a limited product sits in the cart;
9. signed in, `window.customerOrderLimitsV2.customerAuthenticated` is `true` and each rule's `purchased` matches prior orders — buy one unit, complete the order, then reload the product page and confirm `purchased` increased. If `diagnostics.lineItemsSeen` is `0`, the page could not read history itself: confirm `window.CustomerOrderLimits.historyState()` reports `loaded` and that `/account/orders` contains `#customer-order-limit-history` with the expected lines;
10. with a refresh timestamp set in the past, `purchased` drops to zero for orders placed before it, `limitWindowLabel` is set, and the copy names that date; with one set in the future, nothing changes and `refreshAt` still reports the configured value;
11. on a product with a limit of 1: Buy Now from an empty cart adds one unit and reaches checkout; Buy Now again goes straight to checkout without adding; the buttons never stay disabled or spinning; and every message on the page reflects the current cart.

## Enforcement boundary

This is a theme-level storefront safeguard, not server-side authorization. Disabled JavaScript, modified clients, direct API calls, stale tabs, and other sales channels can bypass theme code. Hard enforcement requires an EasyStore server-side app or checkout validation capability.

## Rollback

Set every `customer_order_limit_handle_N` to `''` and every maximum to `0`, or deploy the known-good PR #61 artifact.

# Customer order limits

This feature limits a signed-in customer to a configured number of units for an EasyStore product handle across non-cancelled orders and the current cart.

## Configured limits

| EasyStore product handle | Per-customer maximum |
| --- | ---: |
| `MTG-HOB-BDL-EN` | 6 |
| `MTG-HOB-CBB-EN` | 1 |
| `MTG-HOB-CBB-EN-CASE6` | 1 |
| `MTG-HOB-CBB-EN-PACK` | 2 |
| `MTG-HOB-DNK-EN` | 3 |
| `MTG-HOB-GFB-EN` | 1 |
| `MTG-HOB-PBB-EN` | 12 |
| `MTG-HOB-PRK-EN-SET4` | 3 |
| `MTG-HOB-OBP-EN` | 1 |
| `MTG-HOB-SCN-EN-SET2` | 2 |
| `MTG-MSH-JBB-EN` | 6 |
| `MTG-MSH-CMD-EN-CE-SET4` | 1 |
| `CC-BDL-SCENES3-EN` | 1 |
| `CC-BDL-FRIENDS3-EN-SPM` | 1 |
| `CC-BDL-FRIENDS3-EN-MSH` | 1 |
| `CC-BDL-SPIDERVAULT-EN` | 1 |
| `CC-BDL-UNEXPECTED-EN` | 2 |

Rows supplied with a blank promo maximum are intentionally not configured and remain unlimited. This includes the remaining `MTG-MSH-*`, `MTG-SOS-*`, and `MTG-SPM-*` handles not listed above, plus `CC-BDL-HAPPYHAMPER-EN` and `CC-BDL-HAPPYHAMPER-EN-PBB`.

Every limit counts from **9 Aug 2026 00:00 store time (GMT+8)**, set once as `customer_order_limit_refresh_all`. Orders placed before that date do not consume an allowance, so a customer who bought a limited product earlier may buy it again up to its maximum. No row overrides the shared date; setting `limit_refresh` on a row counts that one limit from a different date. See [Renewing an allowance](#renewing-an-allowance).

## Adding or updating a limit

One limit is one row in `theme/snippets/customer-order-limit-config.liquid`, and that row is the whole change:

```liquid
{% include 'customer-order-limit-row', limit_handle: 'MTG-HOB-BDL-EN', limit_maximum: 6, limit_refresh: '2026-09-01 00:00:00 +0800' %}
```

| Value | Meaning |
| --- | --- |
| `limit_handle` | EasyStore product handle or SKU. Delete the row to make a product unlimited; handles that are not listed are unlimited. |
| `limit_maximum` | units one customer may buy. |
| `limit_refresh` | the date the allowance is counted from. Blank falls back to `customer_order_limit_refresh_all`. |

The row resolves its own refresh window, counts the customer's orders and cart for that handle, and publishes its rule, so nothing else in the theme changes when a product is added, updated, or removed. Handles are normalized to lowercase on both sides of every comparison because EasyStore product URLs use lowercase handles even when administrative values are capitalized.

This replaces the earlier numbered slots, where one limit was spread over seven places in two files — `customer_order_limit_handle_N`, `_maximum_N`, `_refresh_N`, a normalization line, a window block, a history-matching block, a cart-matching block and a rule include. A product added to some of them but not all enforced nothing, and the omission was invisible.

## Renewing an allowance

`limit_refresh` is the date a limit is counted from, so an allowance is measured over a window instead of over every order since the store opened. Once the timestamp has passed, orders placed before it stop counting and every customer starts that limit again from zero. A timestamp in the future changes nothing until it arrives, and a blank one keeps counting every past order forever.

`customer_order_limit_refresh_all` at the top of the configuration covers every row that leaves its own blank, so one line renews the whole store. It is currently `'2026-08-09 00:00:00 +0800'`, which every row inherits. Write timestamps with the store's timezone offset:

```liquid
{% include 'customer-order-limit-row', limit_handle: 'CC-BDL-SCENES3-EN', limit_maximum: 1, limit_refresh: '2026-09-01 00:00:00 +0800' %}
```

A row with no refresh configured must leave the window inert. Comparisons in `customer-order-limit-window.liquid` are against `''` on values forced to strings rather than against `blank`, and the resolved epoch has to land past 1970, because a live store activated a window at epoch 0 from an unconfigured slot and told shoppers their limit counted "since Jan 01, 1970".

`include` shares the caller's scope on EasyStore, so `customer-order-limit-row.liquid` clears its three inputs on the way out. Without that, a row written without `limit_refresh` would inherit the previous row's timestamp and renew a limit that never asked for it.

Renewal is evaluated when the page renders, so it takes effect on the next page load after the timestamp passes. Storefront copy names the date once a window is active — "The limit is 1 unit per customer across orders since Sep 01, 2026" — and each rule publishes `refreshAt` and `limitWindowLabel` so the configuration can be verified in the browser console.

To renew a limit, set the timestamp rather than clearing the maximum: clearing the maximum disables the limit entirely, while a refresh keeps the limit enforced for purchases made from that date onwards.

## Enforcement

Each row makes one pass through the customer's orders and one pass through `cart.items`, combining quantities for every line with the same normalized identifier. Cancelled orders are ignored, and orders older than the row's refresh window are skipped before its line items are read.

A line is matched on **either** its product handle **or** its SKU. A configured value such as `MTG-HOB-SCN-EN-SET2` is both the storefront handle and the SKU, and order line items do not expose the same identifier on every store — matching only `product.handle` counted zero units, which let a customer reorder the same product in order after order. A row only runs for a non-blank handle, so a line item carrying neither identifier reads as `''` and matches nothing. Quantities and the order and line collections each read a fallback field name for the same reason.

Booleans published by these snippets are read by value, not by identity: EasyStore's `json` filter renders a Liquid boolean as `1` or `0`, so a strict `=== true` check is false for every signed-in customer.

The same applies inside Liquid. `order.is_cancelled` is an **integer** on EasyStore — `templates/customers/orders.liquid` compares it with `== 1` — and Liquid treats `0` as truthy, so `{%- raw -%}{% unless order.is_cancelled %}{%- endraw -%}` skipped *every* order and counted zero units for every customer, while the account page visibly listed their orders. Order flags are forced to strings and compared by value. Tests fixture these flags as integers for the same reason: Python booleans in the fixtures made the bug invisible.

`window.customerOrderLimitsV2.diagnostics` reports what the history pass could actually read: `ordersSeen`, `lineItemsSeen`, and an `identifiers` sample in `handle/sku×quantity` form. It is produced by `customer-order-limits.liquid` before any row runs, so it describes the order history itself rather than any one limit. `ordersSeen: 0` for a signed-in customer with orders means the storefront cannot see order history at all; a populated sample whose values never match a configured row means the identifiers differ from what is configured.

## When a page cannot see order history

`customer.orders` carries line items on the account order pages — `templates/customers/orders.liquid` renders them — but a product or cart page can receive the orders list without them, or without orders at all. The inline pass then counts zero units and the limit quietly stops applying across orders, which is how a customer could reorder a limited product after paid and fulfilled orders.

So history is loaded when the page could not read it:

1. `templates/customers/orders.liquid` publishes every non-cancelled line item as JSON in `#customer-order-limit-history` — handle, SKU, order date, quantity, order token, product id, variant id — capped at 500 lines. It does no filtering; the reading page applies its own configured handles and refresh windows, so there is one matching implementation. The ids are published because a line item is only guaranteed to expose `variant_id`: this theme's own order pages read it, while a handle or SKU may be absent. A rule is matched by handle, by SKU, or — for the product whose page is being viewed — by its own product and variant ids.
2. A page whose `diagnostics.lineItemsSeen` is `0` treats history as **unknown**, not as "nothing purchased", and fetches `/account/orders` in the background as the page loads. That list is tab filtered and paginated, so one request only covers the default tab's first page — on a live store that returned zero lines because the default tab held none of the customer's completed orders. The loader therefore walks every tab except cancelled ones — tabs reporting orders first, but a reported count of zero never skips a tab, because the live store rendered a count only for the tab being viewed — follows each tab's pagination, de-duplicates identical lines, and stops at twelve requests. The merged result is cached in `sessionStorage` for five minutes per customer, so it costs one walk per session.
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

The rule reports two different numbers and they must not be confused. `maximum` is what may still be added — net of the cart and of past orders — while `totalMaximum` is the configured ceiling. `contextual: true` marks the pair, and any reader that measures the cart itself must skip its own subtraction for such a limit. Quoting `maximum` as the ceiling is what produced "2 units in cart + 2 units selected = 0 units maximum" on a product limited to 2 per person: nothing was left to add, and that nothing was printed as the limit. The shared formatter now states a ceiling as a clause — "the limit is 2 units per customer", "only 3 units are available" — and the product page repeats the validator's own sentence verbatim rather than rebuilding one, so it agrees with the cart and listing and keeps what it says about earlier orders.

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

Delete the rows from `customer-order-limit-config.liquid` — a configuration with no rows publishes no rules and leaves every purchase path native — or deploy the known-good PR #61 artifact.

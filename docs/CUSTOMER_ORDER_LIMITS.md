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

## Enforcement

Liquid makes one pass through `customer.orders` and one pass through `cart.items`, combining quantities for all variants with the same normalized product handle. Cancelled orders are ignored.

The shared validator integrates with the native theme paths:

- product page, featured product, and quick-view quantity validation;
- Add to Cart and Buy Now;
- listing quick-add;
- cart quantity updates;
- standard checkout, express checkout, and additional checkout controls.

Successful additions and cart updates change the browser-side allowance only after EasyStore's native callback confirms success. Rejected requests do not consume allowance. Cart decreases and removals remain available so an over-limit cart can be corrected.

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

## Preview validation

Before merging or publishing, upload the exact workflow ZIP to an unpublished EasyStore theme and verify:

1. each configured handle permits its maximum but blocks one additional unit;
2. every handle with a blank promo maximum behaves as unlimited;
3. prior non-cancelled order quantities reduce the remaining allowance;
4. multiple variants and cart lines for one handle are combined;
5. Add to Cart, Buy Now, listing quick-add, cart increases, standard checkout, and express checkout are blocked when over limit;
6. cart decreases and removals continue to work;
7. rejected requests do not reduce the remaining allowance;
8. signed out, Add to Cart, Buy Now, listing quick-add, and cart checkout on a limited product open the login page and return to the original page after signing in, with no limit message, disabled control, or clamped quantity shown first;
9. signed in, every purchase path works normally on desktop and mobile and never reaches an account page — check a limited product, an unlimited product, and an unlimited product bought while a limited product sits in the cart;
10. signed in, `window.customerOrderLimitsV2.customerAuthenticated` is `true` and each rule's `purchased` matches prior non-cancelled orders.

## Enforcement boundary

This is a theme-level storefront safeguard, not server-side authorization. Disabled JavaScript, modified clients, direct API calls, stale tabs, and other sales channels can bypass theme code. Hard enforcement requires an EasyStore server-side app or checkout validation capability.

## Rollback

Set every `customer_order_limit_handle_N` to `''` and every maximum to `0`, or deploy the known-good PR #61 artifact.

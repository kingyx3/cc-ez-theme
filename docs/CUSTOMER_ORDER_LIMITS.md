# Customer order limits

This feature limits a signed-in customer to a configured number of units for an EasyStore product handle across non-cancelled orders and the current cart.

## Configured limits

| EasyStore product handle | Per-customer maximum |
| --- | ---: |
| `MTG-HOB-BDL-EN` | 6 |
| `MTG-HOB-CBB-EN` | 1 |
| `MTG-HOB-CBB-EN-CASE6` | 1 |
| `MTG-HOB-CBB-EN-PACK` | 4 |
| `MTG-HOB-DNK-EN` | 3 |
| `MTG-HOB-GFB-EN` | 1 |
| `MTG-HOB-PBB-EN` | 12 |
| `MTG-HOB-PRK-EN-SET4` | 3 |
| `MTG-HOB-OBP-EN` | 2 |
| `MTG-HOB-SCN-EN-SET2` | 2 |
| `MTG-MSH-JBB-EN` | 6 |
| `MTG-MSH-CMD-EN-CE-SET4` | 1 |
| `CC-BDL-SCENES3-EN` | 1 |
| `CC-BDL-FRIENDS3-EN-SPM` | 1 |
| `CC-BDL-FRIENDS3-EN-MSH` | 1 |
| `CC-BDL-SPIDERVAULT-EN` | 1 |
| `CC-BDL-UNEXPECTED-EN` | 2 |
| `late-night-crackers-ep3` | 2 |
| `late-night-crackers-ep4-1` | 4 |
| `late-night-crackers-ep4-2` | 1 |

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

Renewal is evaluated when the page renders, so it takes effect on the next page load after the timestamp passes.

The date is never shown to shoppers. It is store configuration, not something a customer needs to reason about, so storefront copy states the ceiling only — "Limit reached: 1 unit per customer." Each rule still publishes `refreshAt`, `limitWindowLabel` and `windowStart`, so the configuration can be verified in the browser console and the client-side history filter knows which orders to count.

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

A purchase attempted while history is still unknown is **held** rather than measured against an allowance that assumes nothing was bought: the shopper sees "Checking your purchase limit. Try again in a moment." Because the load starts at page load, that window is normally too short to see.

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

## What a shopper is told

Every message is one short lead naming the ceiling, followed by at most one clause accounting for it. Nothing states the same number twice, and no message names the refresh date.

| Situation | Message |
| --- | --- |
| Nothing left, bought some and holding some | `Limit reached: 3 units per customer. You have 2 ordered and 1 in your cart.` |
| Nothing left, all of it in the cart | `Limit reached: 2 units per customer. You have 2 in your cart.` |
| Nothing left, all of it on past orders | `Limit reached: 2 units per customer. You have already ordered 2.` |
| Nothing left, neither | `Limit reached: 1 unit per customer.` |
| Room left, some of it spent on orders | `You can add 1 more unit (3 units per customer, 2 already ordered).` |
| Room left, only the cart holding any | `You can add 1 more unit (3 units per customer).` |
| Room left, nothing consumed at all | `Limit: 3 units per customer.` |
| Cart blocks checkout, none allowed | `Limit reached: 3 units per customer. You have already ordered 3, so remove this item to check out.` |
| Cart blocks checkout, orders took some | `Reduce this item to 1 unit to check out (3 units per customer, 2 already ordered).` |
| Cart blocks checkout, nothing ordered | `Reduce this item to 3 units to check out.` |

Two rules decide what follows the ceiling. **Past orders are always accounted for**, because they are the one quantity a shopper cannot see on the page raising the message — told only "you can add 1 more unit (3 units per customer)" after ordering 2, they are left to work out where the other 2 went. **A number is never stated twice**: when nothing has been consumed the ceiling and what may be added are the same figure, so the message names it once.

### One message per form

A product form has two places a limit message can land: the note under the quantity picker (`[data-quantity-limit-message]`) and the alert under the buttons (`.form__message`). They sit a few centimetres apart, so a message written to both reads as the page saying it twice — which is what typing an over-limit quantity and then clicking **Buy Now** did. Add to Cart hid the fault: the validator sets `max` on the quantity input, so the browser's own constraint validation blocks that submit before any theme code runs. Buy Now is a `type="button"`, so nothing blocked it, and the delegated guard wrote the alert beside the note that was already showing.

The note owns limit copy:

- a blocked purchase attempt writes the note when the form has one, and falls back to the alert when it does not (a listing card, for instance);
- showing the note hides an alert that holds limit copy;
- whoever writes the alert records whether what it wrote was limit copy, in `data-purchase-limit-message`. Reading the alert's wording instead does not work — the copy often names no limit at all ("You can add 2 more units (2 units per order)."), so the note appeared beside an alert it was meant to replace.

A rejection from the store is the exception and stays in the alert. `setSubmitting` revalidates immediately after it renders, and a quantity that no longer breaches the rejected maximum clears the note — routing it there lost the message entirely. If that revalidation does raise the note, it hides the alert on its way in, so the two still never show the same sentence at once.

The server-rendered Liquid in `customer-order-limit-rule.liquid` mirrors these branches, including the case where an allowance spent entirely on past orders leaves nothing to reduce to — that one asks for the item to be removed rather than telling a shopper to "reduce this item to 0 to check out".

The shared formatter in `purchase-limit-feedback.js` phrases store-raised limits the same way, varying only the ceiling phrase: `only 5 units in stock`, `4 units per order`, `3 units for this promotion`. A limit that already phrased its own copy is quoted verbatim rather than rebuilt, so the product page, listing and cart agree.

This replaced copy that spent three sentences on one number — "Customer purchase limit reached. You have already purchased 2 units of the 2 units allowed per customer across orders." — where the ceiling, the tally and the rule were each stated in full and the shopper had to read to the end to learn they could not buy.

The rule reports two different numbers and they must not be confused. `maximum` is what may still be added — net of the cart and of past orders — while `totalMaximum` is the configured ceiling. `contextual: true` marks the pair, and any reader that measures the cart itself must skip its own subtraction for such a limit. Quoting `maximum` as the ceiling is what produced "2 units in cart + 2 units selected = 0 units maximum" on a product limited to 2 per person: nothing was left to add, and that nothing was printed as the limit. The shared formatter now names a ceiling as a short phrase — "2 units per customer", "only 3 units in stock" — and the product page repeats the validator's own sentence verbatim rather than rebuilding one, so it agrees with the cart and listing and keeps what it says about earlier orders.

## Signed-out shoppers

A limit counts units per customer across orders, so it can only be measured for a signed-in customer. Guests are therefore never measured against an allowance. Instead, a purchase attempt on a limited product sends the shopper to `/account/login?redirect_uri=<current page>`, where the login page also links to registration:

- Add to Cart, Buy Now, and listing quick-add on a limited product;
- cart checkout — standard, express, and additional controls — while a limited product is in the cart.

For a guest, no limit rule contributes a quantity maximum, disables a purchase or checkout control, clamps a cart quantity input, or replaces native purchase-limit copy. Once the customer signs in, the same rules apply with their real order history.

The redirect is scoped to the product being bought. A limited product sitting in the cart never diverts Add to Cart or Buy Now for a different product; only the cart's own checkout controls consider the whole cart.

## Coming back after signing in

EasyStore ignores `redirect_uri`. It signs the customer in through its own flow — the login POST, then the OTP step it renders at `/account/auth` — and then lands them on the account area, which is why a shopper who clicked Buy Now arrived at their **order history** instead of the product they were buying. No theme setting changes where the platform lands them, so `assets/account-login-redirect.js` completes the trip from the theme side:

1. on a login, register, or recovery page, a guest's `redirect_uri` is recorded in `sessionStorage` under `cc:pending-login-redirect` with a timestamp;
2. on the first page that proves the shopper is signed in — the account page EasyStore chose — the recorded target is read, removed, and navigated to with `location.replace`, so Back returns to the product rather than to the account page.

**A shopper who opens the login page themselves is remembered too.** Nothing sent them there, so there is no `redirect_uri`, and EasyStore's landing page is the same order history — rarely where they were going. The page they came from is, so `document.referrer` is recorded instead, under three conditions:

- a `redirect_uri` always wins, and a target a purchase surface already recorded is never displaced by it;
- the referrer must be same-origin and pass the same target rules as everything else, which refuses any `/account` page — so once the platform's own steps have posted and the referrer names one of them, it is ignored;
- it is only recorded for a shopper the page proves is signed out, by the header's `[data-customer-authenticated="false"]`. A customer who opens the login page for some other reason is not bounced back out of it.

**With no referrer either** — a typed URL, a bookmark, a referrer policy that strips it, or one pointing off-site — the shop's front page `/` is recorded instead. A list of past orders is not somewhere to shop from. It is the least specific target there is, so it is also the one target a page the shopper actually came from may still replace while they are signing in; nothing else may.

Because the default is recorded during the sign-in rather than decided on arrival, a customer who simply opens their order history has nothing recorded and is left exactly where they asked to be.

**The landing page must not be seen on the way past.** The module is deferred, so it runs at `DOMContentLoaded` — a paint too late, and the order history was visible for a moment before the product appeared. `snippets/login-redirect-boot.liquid` is included in the layout's `<head>`, immediately after the character set and before anything the platform injects, so a shopper coming back is sent on before the body is parsed. It is inline because an external script early enough to beat the paint would block parsing on every page of the store to serve one.

Running that early costs it the body: the markup check below cannot run there. So it acts on one page only — an `/account` page that is **not** one of EasyStore's sign-in steps, which is where the platform lands a customer whose sign-in has finished. Every other page is left to the deferred module, which has the markup in front of it. The two share an entry, a half-hour window, and the same refusals; `tests/test_login_redirect_completion.py` pins the copies together, and `e2e/login-redirect.spec.js` runs the snippet's own script the way the layout runs it.

The module loads from `layout/theme.liquid` on every page, because the platform picks the landing page and it need not be an account page.

**Signed in is not the same as finished signing in.** EasyStore counts a shopper who has passed the mobile-number step as a customer while the one-time code is still outstanding, so `body.customer-logged-in` and the header's signed-in marker are both rendered on the OTP step itself. The first deployed version read them there and threw the shopper to the product page having typed nothing but their mobile number — unauthenticated, with the code unconfirmed. A page that is still asking for a step is therefore never a page to leave, whatever the markers say, and that is decided two ways because neither is sufficient alone:

- the path — `/account/login`, `register`, `recover`, `auth` (where the code is confirmed), `activate`, `reset`;
- the markup — `#otp-form` and `.otp-input`, the platform widget's own cells, plus the password and account fields the theme's login and register templates render. The OTP step renders no form of its own and its URL belongs to EasyStore, so the markup has to carry the check where the path cannot.

Both modules read that markup and nothing more: no value is written into a cell, no event is dispatched, and no listener is attached to one. That line is what the "Customer already exists (phone)" outage was about, and it is not crossed here.

The rest of the safeguards:

- the target is consumed on the first signed-in page load whether or not it is used, so it can never divert a later, unrelated sign-in, and it expires after 30 minutes regardless;
- only a same-origin path is followed. A protocol, a protocol-relative `//host`, a backslash host, a control character, or an `/account` path is discarded, so the parameter cannot be used to bounce a shopper off the store or back into the sign-in flow;
- landing on the target already — should the platform ever start honouring the parameter — clears the entry and navigates nowhere;
- `sessionStorage` being unavailable means the redirect is simply not completed; nothing throws and no purchase path changes.

The platform's login form is deliberately untouched: no field is added to it and no value is written into it. Theme scripts writing into EasyStore's account forms is what broke signup with "Customer already exists (phone)", and landing on the right page one paint later is not worth repeating that.

`e2e/login-redirect.spec.js` runs the module through the real page loads — login page, account landing, product — against pages it serves itself, so it needs no storefront and no store account. `tests/test_login_redirect_completion.py` covers the wiring: both asset trees, the layout include, and the parameter name shared with `customer-order-limits.js` and `cart.js`.

## The attempt that signing in interrupted

The click a guest made does not survive the round trip through the platform's login, so it is recorded when they are sent away and answered when they come back. Without that, a customer whose allowance was already spent on previous orders returned to a page that said nothing about it: the button looked ready, and only pressing it a second time produced "Customer purchase limit reached".

Every surface that redirects a guest names what was being bought — `redirectToLogin({ handle, quantity, surface })` — and the attempt is kept in `sessionStorage` under `cc:pending-purchase-intent` with a timestamp. `surface` is one of `product` (Add to Cart), `buy-now`, `listing` (quick-add), or `cart` (checkout with a limited product in the cart).

On the first page that proves the shopper is signed in, the attempt is read, removed, and answered with the message that click would have produced, on the surface that click came from: the product form's own error for a product page, the listing alert for quick-add, and the cart error for checkout. A shopper who can still buy what they asked for is told nothing.

What the answer is careful about:

- **it waits for history.** Answering before the `/account/orders` pass lands would measure against an allowance that assumes nothing was ever bought — the reverse of the mistake worth making — so it waits for the load to land or to give up (`customer-order-limits:history` or `customer-order-limits:history-unavailable`);
- **it needs proof of signing in**, not merely the absence of proof of signing out, so an attempt is never answered for someone whose allowance cannot be measured. A guest who abandons the sign-in keeps their attempt until they sign in or it expires after 30 minutes;
- **it skips `/account` pages and any page still asking for a step.** The first is where EasyStore lands a freshly signed-in customer, and `account-login-redirect.js` is about to move them on; the second is a sign-in that has not finished, where the shopper counts as a customer while the one-time code is outstanding. The answer belongs on the page they actually return to;
- **it is consumed once**, whether or not it is used, so an attempt answered on one page can never resurface on the next;
- **Buy Now with the allowance already in the cart says nothing.** That button checks out with what the cart holds rather than failing, so a warning there would contradict what pressing it does.

**The quantity comes back too.** The page is freshly rendered after login, so the field says 1 whatever the shopper chose before they were sent away. Their number is put back, capped at what may still be bought: five asked for with two left becomes 2, and the message says why. A field left at 1 makes them type it again; a field left at 5 cannot be submitted at all. With nothing left to buy there is no quantity worth offering, so the field keeps its 1 beside the message and the disabled button. The restore writes to the product form's own quantity field and emits the same `change` event the theme's plus button emits — a cart line is only ever changed by a request to the store, never by writing into it.

Nothing is bought automatically on the way back. The shopper returns to the page they were on, with the quantity they chose, is told if the purchase cannot go through, and presses the button themselves otherwise.

`e2e/purchase-limit-after-login.spec.js` drives the real module through the real page loads for each surface — product page, listing, cart, and the account page in between — against pages it serves itself, including the account order page the history loader reads. `tests/test_purchase_intent_after_login.py` covers what behaviour cannot see: that every redirecting surface names its attempt, and that the answer stays confined to a shopper whose allowance can be measured.

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

Without the console: buy one unit of a product whose limit is 1, complete the order, then reload its product page. Add to Cart should be disabled with "Limit reached: 1 unit per customer", and Buy Now should go straight to checkout rather than adding a second unit.

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
10. with a refresh timestamp set in the past, `purchased` drops to zero for orders placed before it and `limitWindowLabel` is set, while no message on the page names the date; with one set in the future, nothing changes and `refreshAt` still reports the configured value;
11. on a product with a limit of 1: Buy Now from an empty cart adds one unit and reaches checkout; Buy Now again goes straight to checkout without adding; the buttons never stay disabled or spinning; and every message on the page reflects the current cart.

## Enforcement boundary

This is a theme-level storefront safeguard, not server-side authorization. Disabled JavaScript, modified clients, direct API calls, stale tabs, and other sales channels can bypass theme code. Hard enforcement requires an EasyStore server-side app or checkout validation capability.

## Rollback

Delete the rows from `customer-order-limit-config.liquid` — a configuration with no rows publishes no rules and leaves every purchase path native — or deploy the known-good PR #61 artifact.

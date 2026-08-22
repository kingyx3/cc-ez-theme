# EasyStore Checkout → HubSpot Cart sync

This is the endpoint and data-contract reference for the Cart stage of the CRM sync.

## Source of truth

EasyStore exposes cart / checkout sessions through the **Checkout** resource:

- `GET /api/3.0/checkouts.json` — list Checkout sessions
- `GET /api/3.0/checkouts/:cart_token.json` — retrieve one Checkout

EasyStore's Checkout resource includes `id`, `token`, `cart_token`, `email`, `currency_code`, `subtotal_price`, `total_discount`, `total_price`, `total_amount_include_transaction`, `financial_status`, `line_items`, addresses, `created_at`, and `checkout_url`.

The integration maps:

- EasyStore Checkout → HubSpot Cart
- EasyStore `checkout.cart_token` → HubSpot `hs_external_cart_id`
- EasyStore `checkout.financial_status` → HubSpot Cart `hs_external_status`
- EasyStore `checkout.checkout_url` → HubSpot Cart `hs_cart_url`
- EasyStore Checkout totals / currency / discounts → native HubSpot Cart properties when available
- EasyStore Checkout `line_items` → product-backed HubSpot Cart Line Items

`cart_token` is the only current external Cart identity. Checkout `id`, Checkout `token`, and Order IDs must not replace it.

Orders are **not** a Cart data source. Order data may only be used after a real Checkout-backed Cart exists to attach Cart → Order through the shared `order.cart_token`.

## Carts versus abandoned carts

Only the **unpaid, unconverted subset** of EasyStore Checkouts becomes a HubSpot Cart. A paid or converted Checkout is counted and skipped, because the Order stage already carries it and a Cart alongside it would double-count the revenue.

That subset is narrowed once more, to the **recoverable** sessions: those holding line items and naming a shopper (an EasyStore customer reference, an email, or a usable mobile). `checkouts.json` is not the abandoned checkout list EasyStore's admin shows — it is every session the storefront ever opened. Run 32539291543 answered **1267** records where the admin list showed **15**; 717 of them held line items and only 41 carried an email, the rest being anonymous browse sessions with nothing in them and nobody to send them to. Each exclusion is counted (`checkouts_without_line_items`, `checkouts_without_a_contactable_buyer`, `easystore_checkouts_recoverable`) rather than passed over silently, and `recoverable_only=False` restores the write-everything behaviour if a store ever wants it.

Nothing is ever deleted here: a Cart is written or left alone. Carts already in HubSpot that a run does not qualify — earlier runs' records, and sessions that have left the collection — are reported as `hubspot_carts_not_qualified_by_this_run` for an operator to act on.

Because EasyStore's own word for that state differs per store, the abandoned subset is also written to the Cart as a plain flag a HubSpot list or report can filter on: `easystore_cart_is_abandoned` is `true` while a Checkout is unpaid and unconverted, and `false` once it has been paid, completed, or turned into an order. A Checkout carrying an order reference, a `completed_at`, or a settled status in `financial_status`, `payment_status`, `status`, `state` or `checkout_status` is not abandoned — settled includes partial payments, partial refunds and authorizations, because money moved; `pending` is deliberately not settled, because nothing has been collected and the cart is still worth recovering. That single predicate lives in `scripts/easystore_hubspot_carts.py` and is what both the counters and the Cart property use.

### Why every Cart in the CRM reads `unpaid`

This is the source, not the mapping. `checkouts.json` serves open sessions only:

- `financial_status` is the **only** state field on the payload. Run 32539291543 observed exactly 18 keys across 1267 records, and `status`, `state`, `checkout_status`, `completed_at` and `order_id` are all absent — the endpoint has no notion of completion to report.
- a session that converts leaves the collection rather than changing status inside it. That run classified 1267 of 1267 as abandoned and 0 as converted, and none of the store's 27 orders shared a `cart_token` with any listed Checkout (`cart_order_associations_ensured: 0`).

So the Cart object holds the abandoned funnel and nothing else, which is what it is for. To keep this checkable rather than assumed, `cart-sync-summary.json` reports `easystore_checkout_status_counts`: the distribution of the raw status values EasyStore served, counted before anything is filtered. A paid session appearing in this collection would show up there, would be skipped rather than written, and annotates the run.

One consequence worth knowing: a Cart written while unpaid is not revisited once its Checkout leaves the collection, so a Cart that converts later keeps the status it was last seen with. `order.cart_token` remains the bridge for attaching the resulting Order.

## EasyStore list request

The published EasyStore documentation names the correct Checkout endpoint, but its Checkout list parameter table currently contains obvious Product endpoint copy/paste content: it describes `collection_ids`, `skus`, `visibility`, `published_at_*`, and even labels the operation "List products".

Because those parameters are not trustworthy as Checkout-specific contract, production intentionally sends only the two generic pagination parameters that are unambiguous:

```text
GET /api/3.0/checkouts.json?page=1&limit=250
EasyStore-Access-Token: <token>
```

`page` is still sent because it is one of the two documented parameters and costs nothing when ignored; what changed is that the sync no longer *depends* on it.

The sync does **not** send:

- `sort=id.desc`
- `created_at_min`
- `created_at_max`
- `published_at_*`
- `collection_ids`
- `skus`
- `visibility`
- or any other Product-style filter copied into the Checkout documentation block.

**This endpoint mostly does not answer.** Across observed production runs it served the collection roughly once in eight attempts; the rest timed out, sometimes on page 1 at every page size. Two things follow.

First, the read is patient: four attempts of 60s per page size, with backoff. In the worst case that costs about twelve minutes, which a background sync can afford far more easily than another run that writes no Carts.

Second, the page sizes are tried **largest first** — `250`, then `50`, then `1`. When this endpoint did answer, `limit=250` returned the store's whole collection of 1246 Checkouts in one request, while `limit=50` returned 50 and left page 2 (the only way to ask for the rest) unusable. The one request that succeeds should therefore be the one that can return everything, so a single lucky window is enough. `50` is the documented maximum and `1` is the smallest possible request; both are kept as fallbacks for a store that cannot serve a large one.

A page size that never answers is recorded and the next one starts again from page 1, so a snapshot is never stitched together from two of them.

Only a transport-level failure moves on: a timeout, a refused connection, a 429 or a 5xx that survived its retries. An HTTP 4xx is a request or credential problem — most likely a token without checkout scope — and fails the step immediately rather than being retried in a different shape or hidden behind a green run.

The sync never switches to Orders, Admin APIs, or guessed route names to fill Carts.

## When EasyStore cannot serve Checkouts

An unreachable Checkout endpoint is an outage in one upstream endpoint, not a broken CRM sync. Products, Customers, Orders and reconciliation have already been written by the time the Cart stage runs, and failing the step over the outage leaves a red run that says nothing about the data that did land, while hiding the next real failure.

So on an outage the Cart stage:

- skips every Cart and Cart Line Item write, leaving existing HubSpot Carts exactly as they are;
- still refreshes Cart→Order links from `order.cart_token`, which needs no Checkout read;
- annotates the run with `::warning title=EasyStore Checkout API unavailable::` naming every request that was tried;
- reports `easystore_checkout_status: unavailable` in `cart-sync-summary.json`, with `easystore_checkout_error` and one `easystore_checkout_collection_attempts` line per request tried — the list matters because a single joined message truncates exactly where the useful part is, namely which page and limit failed;
- exits successfully.

Set `EASYSTORE_CHECKOUTS_REQUIRED=1` (or pass `--require-checkouts`) to make that outage fail the step instead. Do that once the endpoint is known to be reliable.

Everything else still fails loudly: an unrecognized response shape, a detail response without `line_items`, a duplicate Cart identity, a bad product reference, and every HubSpot write error.

## Pagination: page 2 of this endpoint is not usable

Once the endpoint started answering, page 2 turned out to be worthless in two different ways: it has come back identical to page 1, and it has hung until it timed out. Paging therefore cannot prove a full snapshot, so `limit` does it instead: **an answer shorter than the limit it asked for is the whole collection**, and the proof only ever asks page 1.

Neither bad page 2 discards the page that did arrive. A repeated page proves nothing new, and one unanswered page does not unsay the records already in hand — throwing them away means syncing no Carts at all. Only **page 1** failing means there is nothing to sync, and that is the outage path below.

The reader:

1. requests page 1 with the first page size that answers;
2. continues page-by-page using only `page` + `limit`, stopping on a short page, on a page whose records repeat one already seen, or on a page that does not answer;
3. when pagination stopped without the collection ending *and* the pages that arrived came back full, re-asks page 1 with a larger `limit` (250, then 1000) until an answer is shorter than its limit;
4. buffers the collection before any HubSpot Cart mutation;
5. fetches `GET /api/3.0/checkouts/:cart_token.json` when a list record omits `line_items`;
6. rejects a detail response that still does not provide `line_items`;
7. only then passes the Checkout snapshot to the Cart writer.

`easystore_checkout_pagination_outcome` records which of the three ended pagination.

An answer **longer** than the limit it asked for also proves the collection: `limit` is not acting as a cap, so EasyStore served everything it has. That is what this store does — `limit=50` returns 50, `limit=250` returns all 1246, and `limit=1000` is refused outright with an HTTP 400. Pagination therefore ends on an over-answer without asking again, and a refused escalation after one does not unsay it.

Two answers are ambiguous rather than complete, and are reported as such instead of being claimed:

- a larger limit returning **exactly** the count a smaller saturated limit returned — the store may hold that many Checkouts, or the endpoint may be capping `limit`;
- every limit up to the largest coming back saturated.

Either way the Checkouts that did arrive are still synchronized, `easystore_checkout_snapshot_proven_complete` is `false`, `easystore_checkout_snapshot_completeness` says why, and the run is annotated with `::warning title=EasyStore Checkout snapshot not proven complete::`. A rejected escalation (for instance an HTTP 400 on an over-large `limit`) is recorded the same way and does not fail the step — it only leaves completeness unproven.

Syncing a short snapshot is safe because the Cart writer only touches the Carts in front of it: it reconciles Line Items **within** each Cart it upserts and never deletes a Cart missing from the snapshot. A short snapshot therefore syncs fewer Carts rather than damaging the ones already in HubSpot, and refusing it would mean syncing no Carts at all for as long as `page` is ignored.

## Checkout lines whose product is gone

Open and abandoned Checkouts reach back over the whole catalogue's history, so some name variants that have since been deleted or unpublished and can no longer have a HubSpot Product. The Order stage still fails on an unmatched line — an Order's revenue must be product-backed to be worth anything — but the Cart stage skips the line and keeps the Cart. Losing every Cart over one retired variant is a far bigger loss than losing that line, and a Cart with no lines at all still carries its value, its shopper and its recovery URL.

Those lines are reported, not silently dropped: `cart_lines_without_a_hubspot_product`, `carts_with_lines_without_a_hubspot_product`, and up to 25 distinct SKUs in `cart_line_skus_without_a_hubspot_product`. A SKU appearing there for a product that *should* be live means the Product stage missed it.

For a Cart with a skipped line, stale Cart Line Item removal is turned off. Once a line is missing from the desired set for that reason, "gone from the Checkout" and "product retired from the catalogue" look identical, and deleting on that guess would throw away a Cart line the shopper really had.

## HubSpot mapping

HubSpot Cart objects are written through:

- Cart objects: `/crm/v3/objects/carts`
- Cart properties/schema: `/crm/v3/properties/cart`

Association IDs used by the sync:

- Cart → Contact: `586`
- Cart → Line Item: `590`
- Cart → Order: `592`

### Cart → Contact resolution

The shopper is resolved by **EasyStore customer ID first**, then by **normalized mobile**, because that is the CRM's contact identity, and then by **email**.

The customer ID is the direct link a store without guest checkout should have: an identity EasyStore assigned, not a value the shopper typed into a form. The contact carries it as `easystore_customer_id`, written by the customer stage. The catch is that `checkouts.json` does not expose it — run 32539291543 observed 18 keys across 1267 records and none of them referenced a customer — so the checkout stage probes up to `CHECKOUT_CUSTOMER_PROBE_LIMIT` recoverable sessions on the detail route and reports what it found as `easystore_checkout_customer_reference`, alongside the keys it saw in `easystore_checkout_detail_keys_seen`. The probe is diagnostic: it never fails the stage, and the lookup is already wired, so the direct association starts working the moment a reference appears in the payload.

Failing that, the typed values are what there is. An abandoned Checkout is usually a session that got as far as an email and no phone, so mobile alone leaves Carts unlinked that HubSpot could resolve: run 32539291543 linked 26 of 1267 Carts, with a phone present on only 31 of them and an email on 41.

Email is an association key only. Contacts are still created and deduplicated by mobile in the customer stage, and this stage never creates a Contact from a Checkout — an anonymous cart has no shopper to record.

An identity that matches more than one Contact is never guessed: it is reported and skipped. Every Cart written by the stage falls into exactly one outcome, and those outcomes sum to the Carts written (`cart_contact_association_accounted_for`, counting a link once however it was resolved), so an unlinked Cart always has a stated reason:

- `cart_contact_associations_by_easystore_customer_id`
- `cart_contact_associations_by_mobile`
- `cart_contact_associations_by_email`
- `carts_with_ambiguous_contact_mobile`
- `carts_with_ambiguous_contact_email`
- `carts_with_no_shopper_identity` — the Checkout carries neither a usable mobile nor an email
- `carts_whose_shopper_is_not_a_hubspot_contact` — it carries one, and no Contact holds it

The association call is an idempotent `PUT`, so a rerun re-affirms every link rather than duplicating it.

Every Checkout merchandise line becomes its own product-backed HubSpot Line Item associated to the Cart. These are distinct records from Order Line Items.

The existing SKU mapper also supports EasyStore lines without a literal SKU when both `product_id` and `variant_id` are present, using the integration's stable synthetic identity `ES-<product_id>-<variant_id>`.

## Runtime diagnostics

`cart-sync-summary.json` reports, among other values:

- `easystore_checkout_source`
- `easystore_checkout_collection_endpoint`
- `easystore_checkout_detail_endpoint_template`
- `easystore_checkout_collection_query`
- `easystore_checkout_status` (`available` or `unavailable`)
- `easystore_checkout_error` and `easystore_checkout_collection_attempts`
- `easystore_checkout_page_sizes_tried_in_order` and `easystore_checkout_page_size_used`
- `easystore_checkout_page_parameter_honored` and `easystore_checkout_pagination_outcome`
- `easystore_checkout_snapshot_proven_complete` and `easystore_checkout_snapshot_completeness`
- `easystore_checkout_product_style_filters_sent`
- `easystore_checkout_pages_read`
- `easystore_checkout_details_fetched`
- `easystore_checkouts_buffered`
- `easystore_checkouts_abandoned_or_open`
- `easystore_checkouts_completed_or_paid`
- `hubspot_cart_abandoned_property`
- `hubspot_cart_upserts_skipped` and `hubspot_cart_line_item_sync_skipped`
- `hubspot_carts_created`
- `hubspot_carts_updated`
- `hubspot_cart_line_items_created`
- `hubspot_cart_line_items_updated`
- `easystore_checkout_status_counts` and `easystore_checkout_status_field_read`
- `easystore_checkout_customer_reference` and `easystore_checkout_detail_keys_seen`
- `easystore_checkouts_recoverable`, `checkouts_without_line_items`, `checkouts_without_a_contactable_buyer` and `abandoned_cart_filter_applied`
- `hubspot_carts_not_qualified_by_this_run`
- `easystore_checkouts_abandoned`, `easystore_checkouts_converted` and `checkouts_skipped_as_completed`
- `cart_contact_associations_ensured`, `cart_contact_associations_by_easystore_customer_id`, `cart_contact_associations_by_mobile` and `cart_contact_associations_by_email`
- `carts_with_ambiguous_contact_mobile`, `carts_with_ambiguous_contact_email`, `carts_with_no_shopper_identity`, `carts_whose_shopper_is_not_a_hubspot_contact` and `cart_contact_association_accounted_for`
- `cart_order_associations_ensured`
- `cart_lines_without_a_hubspot_product`, `carts_with_lines_without_a_hubspot_product` and `cart_line_skus_without_a_hubspot_product`
- `cart_source_is_orders`

The expected production values include `easystore_checkout_source: public_api_checkouts`, `easystore_checkout_collection_query: page,limit only`, and `cart_source_is_orders: false`.

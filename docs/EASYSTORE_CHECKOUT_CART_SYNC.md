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

HubSpot's Cart object represents a shopping session whose items can later be purchased or abandoned. The CRM therefore synchronizes **all real EasyStore Checkout sessions**, not only unpaid ones.

- `financial_status=unpaid` (or another still-open source state) is the abandoned / open Cart subset.
- paid or completed Checkouts still remain HubSpot Carts with their source status and may be associated with the resulting HubSpot Order.

Because EasyStore's own word for that state differs per store, the abandoned subset is also written to the Cart as a plain flag a HubSpot list or report can filter on: `easystore_cart_is_abandoned` is `true` while a Checkout is unpaid and unconverted, and `false` once it has been paid, completed, or turned into an order. A Checkout carrying an order reference, a `completed_at`, or a settled status in `financial_status`, `payment_status`, `status`, `state` or `checkout_status` is not abandoned. That single predicate lives in `scripts/easystore_hubspot_carts.py` and is what both the counters and the Cart property use.

This avoids an empty HubSpot Cart object when the store currently has only converted / paid Checkouts.

## EasyStore list request

The published EasyStore documentation names the correct Checkout endpoint, but its Checkout list parameter table currently contains obvious Product endpoint copy/paste content: it describes `collection_ids`, `skus`, `visibility`, `published_at_*`, and even labels the operation "List products".

Because those parameters are not trustworthy as Checkout-specific contract, production intentionally sends only the two generic pagination parameters that are unambiguous:

```text
GET /api/3.0/checkouts.json?page=1&limit=50
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

Each request is retried once with backoff, so two attempts of 30s each, and the page size falls back from EasyStore's documented maximum of `50` to the smallest possible request of `1`, because this production store has served read timeouts on this endpoint. A page size that never answers is recorded and the next one starts again from page 1, so a snapshot is never stitched together from two of them.

Only a transport-level failure moves on: a timeout, a refused connection, a 429 or a 5xx that survived its retries. An HTTP 4xx is a request or credential problem — most likely a token without checkout scope — and fails the step immediately rather than being retried in a different shape or hidden behind a green run.

The sync never switches to Orders, Admin APIs, or guessed route names to fill Carts.

## When EasyStore cannot serve Checkouts

An unreachable Checkout endpoint is an outage in one upstream endpoint, not a broken CRM sync. Products, Customers, Orders and reconciliation have already been written by the time the Cart stage runs, and failing the step over the outage leaves a red run that says nothing about the data that did land, while hiding the next real failure.

So on an outage the Cart stage:

- skips every Cart and Cart Line Item write, leaving existing HubSpot Carts exactly as they are;
- still refreshes Cart→Order links from `order.cart_token`, which needs no Checkout read;
- annotates the run with `::warning title=EasyStore Checkout API unavailable::` naming every request that was tried;
- reports `easystore_checkout_status: unavailable` with `easystore_checkout_error` in `cart-sync-summary.json`;
- exits successfully.

Set `EASYSTORE_CHECKOUTS_REQUIRED=1` (or pass `--require-checkouts`) to make that outage fail the step instead. Do that once the endpoint is known to be reliable.

Everything else still fails loudly: an unrecognized response shape, a detail response without `line_items`, a duplicate Cart identity, a bad product reference, and every HubSpot write error.

## Pagination: this endpoint ignores `page`

Once the endpoint started answering, it turned out to serve page 2 identical to page 1 — `page` does nothing. Paging therefore cannot prove a full snapshot, so `limit` does it instead: **an answer shorter than the limit it asked for is the whole collection.**

The reader:

1. requests page 1 with the first page size that answers;
2. continues page-by-page using only `page` + `limit`, stopping either on a short page or on a page whose records repeat one already seen;
3. when `page` was ignored *and* the one page came back full, re-asks page 1 with a larger `limit` (250, then 1000) until an answer is shorter than its limit;
4. buffers the collection before any HubSpot Cart mutation;
5. fetches `GET /api/3.0/checkouts/:cart_token.json` when a list record omits `line_items`;
6. rejects a detail response that still does not provide `line_items`;
7. only then passes the Checkout snapshot to the Cart writer.

Two answers are ambiguous rather than complete, and are reported as such instead of being claimed:

- a larger limit returning **exactly** the count a smaller saturated limit returned — the store may hold that many Checkouts, or the endpoint may be capping `limit`;
- every limit up to the largest coming back saturated.

Either way the Checkouts that did arrive are still synchronized, `easystore_checkout_snapshot_proven_complete` is `false`, `easystore_checkout_snapshot_completeness` says why, and the run is annotated with `::warning title=EasyStore Checkout snapshot not proven complete::`. A rejected escalation (for instance an HTTP 400 on an over-large `limit`) is recorded the same way and does not fail the step — it only leaves completeness unproven.

Syncing a short snapshot is safe because the Cart writer only touches the Carts in front of it: it reconciles Line Items **within** each Cart it upserts and never deletes a Cart missing from the snapshot. A short snapshot therefore syncs fewer Carts rather than damaging the ones already in HubSpot, and refusing it would mean syncing no Carts at all for as long as `page` is ignored.

## HubSpot mapping

HubSpot Cart objects are written through:

- Cart objects: `/crm/v3/objects/carts`
- Cart properties/schema: `/crm/v3/properties/cart`

Association IDs used by the sync:

- Cart → Contact: `586`
- Cart → Line Item: `590`
- Cart → Order: `592`

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
- `easystore_checkout_page_parameter_honored`
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
- `cart_contact_associations_ensured`
- `cart_order_associations_ensured`
- `cart_source_is_orders`

The expected production values include `easystore_checkout_source: public_api_checkouts`, `easystore_checkout_collection_query: page,limit only`, and `cart_source_is_orders: false`.

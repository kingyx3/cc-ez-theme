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

This avoids an empty HubSpot Cart object when the store currently has only converted / paid Checkouts.

## EasyStore list request

The published EasyStore documentation names the correct Checkout endpoint, but its Checkout list parameter table currently contains obvious Product endpoint copy/paste content: it describes `collection_ids`, `skus`, `visibility`, `published_at_*`, and even labels the operation "List products".

Because those parameters are not trustworthy as Checkout-specific contract, production intentionally sends only the two generic pagination parameters that are unambiguous:

```text
GET /api/3.0/checkouts.json?page=1&limit=1
EasyStore-Access-Token: <token>
```

The sync does **not** send:

- `sort=id.desc`
- `created_at_min`
- `created_at_max`
- `published_at_*`
- `collection_ids`
- `skus`
- `visibility`
- or any other Product-style filter copied into the Checkout documentation block.

The page size is deliberately `1` for the production store because previous Checkout collection requests timed out with larger or filtered requests. If this exact minimal request still times out, the workflow fails and reports that fact; it does not switch to Orders, Admin APIs, guessed routes, or a green empty Cart sync.

## Pagination and snapshot safety

The reader:

1. requests page 1 with `limit=1`;
2. continues page-by-page using only `page` + `limit`;
3. rejects repeated pages so an API that ignores `page` cannot loop forever;
4. buffers the complete collection before any HubSpot Cart mutation;
5. fetches `GET /api/3.0/checkouts/:cart_token.json` when a list record omits `line_items`;
6. rejects a detail response that still does not provide `line_items`;
7. only then passes the Checkout snapshot to the Cart writer.

This prevents partial source data from deleting or reconciling valid HubSpot Cart Line Items.

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
- `easystore_checkout_page_size`
- `easystore_checkout_product_style_filters_sent`
- `easystore_checkout_pages_read`
- `easystore_checkout_details_fetched`
- `easystore_checkouts_buffered`
- `easystore_checkouts_abandoned_or_open`
- `easystore_checkouts_completed_or_paid`
- `hubspot_carts_created`
- `hubspot_carts_updated`
- `hubspot_cart_line_items_created`
- `hubspot_cart_line_items_updated`
- `cart_contact_associations_ensured`
- `cart_order_associations_ensured`
- `cart_source_is_orders`

The expected production values include `easystore_checkout_source: public_api_checkouts`, `easystore_checkout_collection_query: page,limit only`, and `cart_source_is_orders: false`.

# EasyStore Checkout → HubSpot Cart sync

This document is the endpoint/data-contract reference for the Cart stage of the CRM sync.

## Terminology

EasyStore calls the cart-facing Public API resource **Checkouts**. HubSpot calls the corresponding CRM object **Carts**.

The integration therefore maps:

- EasyStore Checkout → HubSpot Cart
- EasyStore `checkout.cart_token` → HubSpot `hs_external_cart_id`
- EasyStore `order.cart_token` → the same HubSpot Cart identity after conversion

Do not substitute EasyStore checkout `id` or checkout `token` for `cart_token`.

## EasyStore endpoints

The documented EasyStore Public API endpoints used by this integration are:

- `GET /api/3.0/checkouts.json` — list checkout/cart sessions
- `GET /api/3.0/checkouts/:cart_token.json` — retrieve one checkout by the cart identity

There is no `/api/3.0/carts.json` route in the current public documentation. The list endpoint supports `page` and `limit`; the sync uses the documented maximum page size of 50 to minimize requests.

The checkout snapshot is all-or-nothing. If any list page fails, or if a checkout that requires detail cannot be hydrated with `line_items`, no Cart or Cart Line Item reconciliation is performed from that incomplete source.

Checkout reads use a short bounded timeout. The checkout API has been observed timing out for the production store even while Products, Customers and Orders continue to work. That outage is treated as an optional capability failure rather than a failure of the entire CRM sync.

## HubSpot endpoints

HubSpot uses different object identifiers for the Cart object API and the properties API:

- Cart objects: `/crm/v3/objects/carts`
- Cart properties/schema: `/crm/v3/properties/cart`

The production wrapper validates this singular/plural contract before syncing.

Cart associations use HubSpot-defined association type IDs:

- Cart → Contact: `586`
- Cart → Line Item: `590`
- Cart → Order: `592`

Every Cart merchandise line is represented by its own product-backed HubSpot Line Item. Cart Line Items are separate records from Order Line Items.

## Degraded mode

If EasyStore cannot provide a complete checkout snapshot:

- Product sync continues normally.
- Customer sync continues normally.
- Order and Order Line Item sync continues normally.
- Cart object upserts are skipped.
- Cart Line Item creation/update/reconciliation is skipped.
- Existing HubSpot Carts can still be associated to newly synced HubSpot Orders using `order.cart_token`.
- The run summary reports `easystore_checkout_status: unavailable` together with the exact endpoint, timeout budget and error reason.

A genuine HubSpot write failure, duplicate identity conflict, SKU/product mismatch or other data-integrity error is **not** degraded and still fails the job.

## Runtime diagnostics

The Cart summary records the exact endpoint contract and read behavior, including:

- `easystore_checkout_collection_endpoint`
- `easystore_checkout_detail_endpoint_template`
- `easystore_checkout_page_size`
- `easystore_checkout_read_timeout_seconds`
- `easystore_checkout_read_retries`
- `easystore_checkout_pages_read`
- `easystore_checkout_details_fetched`
- `easystore_checkouts_buffered`
- `hubspot_cart_collection_endpoint`
- `hubspot_cart_properties_endpoint`
- `hubspot_cart_schema_object_type`
- `hubspot_cart_upserts_skipped`
- `hubspot_cart_line_item_sync_skipped`

These fields are intended to make endpoint drift, API outages and empty checkout collections distinguishable in GitHub Actions without inspecting customer data.

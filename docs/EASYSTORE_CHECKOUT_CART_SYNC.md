# EasyStore Checkout → HubSpot Cart sync

This document is the endpoint/data-contract reference for the Cart stage of the CRM sync.

## Source of truth

EasyStore calls the merchant feature **Abandoned checkouts**. In the published Public API, those cart/checkout records are exposed through the **Checkout** resource:

- `GET /api/3.0/checkouts.json` — list checkout sessions
- `GET /api/3.0/checkouts/:cart_token.json` — retrieve one checkout

EasyStore does not currently publish a separate `/api/3.0/abandoned_checkouts.json`, `/api/3.0/abandoned_carts.json`, or `/api/3.0/carts.json` Public API route.

HubSpot Cart data must therefore come from real EasyStore Checkout records. Orders are **not** a fallback source for Cart properties or Cart Line Items.

The identity mapping is:

- EasyStore `checkout.cart_token` → HubSpot `hs_external_cart_id`

Do not substitute EasyStore checkout `id`, checkout `token`, or an Order ID for `cart_token`.

## What counts as an abandoned Cart

The Public API Checkout resource exposes `financial_status`, `line_items`, addresses, totals, contact details, `created_at`, `checkout_url`, and `cart_token`.

The sync keeps only checkouts that are still incomplete/unpaid. Paid, completed, converted, cancelled, refunded, or voided checkouts are excluded from the active abandoned-cart population.

EasyStore's merchant Help Center states that abandoned checkouts are available for 90 days. The API reader therefore requests only the recent 90-day window using `created_at_min` rather than scanning the store's entire checkout history.

## Read strategy

The production store previously timed out on:

`GET /api/3.0/checkouts.json?page=1&limit=50`

The abandoned-cart reader now:

1. requests `/api/3.0/checkouts.json` with `sort=id.desc` and a 90-day `created_at_min` cutoff;
2. starts with `limit=10`;
3. if the collection request itself fails, restarts the complete snapshot at `limit=5` and then `limit=1`;
4. buffers every list page before any HubSpot Cart write;
5. fetches `GET /api/3.0/checkouts/:cart_token.json` only when an abandoned list record omits `line_items`;
6. fails the Cart stage if the complete checkout snapshot still cannot be read.

A source failure is intentionally **not** converted into a green empty Cart sync. Products, Customers, and Orders run earlier in the workflow, but the workflow reports failure if EasyStore cannot provide the abandoned-checkout data required for Carts.

## HubSpot endpoints

HubSpot uses different object identifiers for the Cart object API and properties API:

- Cart objects: `/crm/v3/objects/carts`
- Cart properties/schema: `/crm/v3/properties/cart`

Cart associations use HubSpot-defined association type IDs:

- Cart → Contact: `586`
- Cart → Line Item: `590`
- Cart → Order: `592`

Every Cart merchandise line is represented by its own product-backed HubSpot Line Item. Cart Line Items are separate records from Order Line Items.

Orders may be consulted only after a real EasyStore Cart exists to attach the Cart→Order relationship using the shared `cart_token`; Order fields never manufacture the Cart itself.

## Runtime diagnostics

The Cart summary reports:

- `easystore_abandoned_checkout_source`
- `easystore_checkout_collection_endpoint`
- `easystore_checkout_detail_endpoint_template`
- `easystore_checkout_window_days`
- `easystore_checkout_created_at_min`
- `easystore_checkout_sort`
- `easystore_checkout_page_size_used`
- `easystore_checkout_page_size_candidates`
- `easystore_checkout_pages_read`
- `easystore_checkout_details_fetched`
- `easystore_checkouts_listed`
- `easystore_abandoned_checkouts_buffered`
- `hubspot_cart_collection_endpoint`
- `hubspot_cart_properties_endpoint`
- `hubspot_cart_schema_object_type`
- `cart_source_is_orders`

These diagnostics distinguish a genuinely empty abandoned-checkout window from a source API failure without exposing customer data.

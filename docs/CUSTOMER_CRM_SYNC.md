# EasyStore CRM sync

`.github/workflows/sync-easystore-customers-hubspot.yml` independently syncs EasyStore commerce/CRM data into HubSpot at **00:00, 06:00, 12:00 and 18:00 Singapore time** and can also be run manually with `workflow_dispatch`.

The workflow runs in dependency order: **Products → Customers → Orders + Line Items**. Products establish catalog identity first, customers establish contact identity second, and the order stage then links purchases to both.

## Required repository secrets

- `EASYSTORE_ACCESS_TOKEN` — an EasyStore Public API access token with:
  - `read_products`
  - `read_customers`
  - `read_orders`
- `HUBSPOT_ACCESS_TOKEN` — a HubSpot access token with:
  - `crm.objects.products.read`
  - `crm.objects.products.write`
  - `crm.objects.contacts.read`
  - `crm.objects.contacts.write`
  - `crm.objects.orders.read`
  - `crm.objects.orders.write`
  - `crm.objects.line_items.read`
  - `crm.objects.line_items.write`
  - `crm.schemas.orders.write`

The existing `EASYSTORE_ADMIN_TOKEN` used by theme deployment is intentionally not reused. EasyStore's documented Public API authenticates with the `EasyStore-Access-Token` header, so this sync has its own least-privilege read credential.

## Products and variants

`scripts/easystore_hubspot_products.py` synchronizes the EasyStore catalog into HubSpot's native Product library.

An **EasyStore variant maps to one HubSpot Product record**. This is deliberate: an EasyStore parent product can have multiple variants with separate SKUs and prices, while a HubSpot Product represents one SKU/unit-price combination. It also lets each EasyStore order line reference the exact HubSpot Product record for the purchased variant.

Product identity is HubSpot `hs_sku`:

- if the EasyStore variant has a SKU, that value is used;
- if the EasyStore variant has no SKU, the sync generates the stable value `ES-<product_id>-<variant_id>`;
- if EasyStore contains duplicate non-blank SKUs, or HubSpot already contains multiple Products with the same SKU, the sync stops before writing products rather than guessing which record owns the SKU.

Fields synchronized are:

| EasyStore | HubSpot Product |
| --- | --- |
| parent `title` + variant `name` | `name` |
| variant `sku` | `hs_sku` |
| variant `price` | `price` |
| parent `description` / `body_html` | `description` |
| variant `cost_price` | `hs_cost_of_goods_sold` |

EasyStore products are paged from `/api/3.0/products.json`. If a product-list response does not include variants, the sync retrieves them from `/api/3.0/products/<product_id>/variants.json`. HubSpot products are scanned in pages of 100 and then created/updated using HubSpot batch endpoints.

## Customer identity and normalization

The normalized mobile number is the only CRM Contact identity key. Email is synchronized as contact data but is never used to decide which HubSpot record belongs to an EasyStore customer.

`scripts/easystore_hubspot_sync.py` normalizes EasyStore `phone` values to an E.164-style `+<country code><subscriber>` value. It uses the customer's EasyStore ISO `country_code` when available and otherwise falls back to repository variable `CUSTOMER_SYNC_DEFAULT_DIAL_CODE`, which defaults to Singapore `65`.

The normalized value is written to both HubSpot `mobilephone` and `phone`. Existing HubSpot contacts are scanned and normalized the same way before matching, so harmless formatting differences do not create a second contact.

If multiple EasyStore customer records share a normalized mobile number, the most recently updated record wins for that run. If multiple HubSpot contacts already share the same normalized number, the contact sync does not guess and reports the conflict.

## Customer fields synchronized

The contact sync uses HubSpot standard contact properties only:

| EasyStore | HubSpot Contact |
| --- | --- |
| `phone` | `phone`, `mobilephone` |
| `first_name` | `firstname` |
| `last_name` | `lastname` |
| `email` | `email` |
| `primary_address.address1/address2` | `address` |
| `primary_address.city` | `city` |
| `primary_address.province` | `state` |
| `primary_address.zip` | `zip` |
| `primary_address.country` or customer `country` | `country` |
| `primary_address.company` | `company` |

HubSpot email uniqueness is respected without turning email into an identity key. If an EasyStore email is already owned by another HubSpot contact, the sync still updates/creates the phone-identified contact but omits that conflicting email and logs a warning.

## Orders and product-backed line items

`scripts/easystore_hubspot_orders.py` synchronizes EasyStore orders after Products and Customers have completed successfully.

The commerce model is:

1. **EasyStore Customer → HubSpot Contact**, keyed by normalized mobile number.
2. **EasyStore Variant → HubSpot Product**, keyed by SKU.
3. **EasyStore Order → HubSpot Order**, keyed by immutable EasyStore order ID.
4. **EasyStore order item → HubSpot Line Item**, backed by the matching HubSpot Product through `hs_product_id`.
5. **HubSpot Order → Contact** association, so purchase history is attached to the customer.
6. **HubSpot Order → Line Item** association, so the order contains the purchased catalog items.

Products themselves are not associated directly to Orders in HubSpot; the product-backed Line Item is the transaction-specific instance that joins catalog data to an order.

### Order identity and idempotency

On the first order-sync run, the script creates a HubSpot Order property group named `easystore_sync` and a unique text property named `easystore_order_id`. The immutable EasyStore order ID is stored there and used to find the same HubSpot Order on every later six-hour run.

If the property already exists but is not configured as unique, the sync stops rather than creating duplicate order identity.

Order fields currently mapped to HubSpot standard Order properties include:

| EasyStore | HubSpot Order |
| --- | --- |
| `id` | custom unique `easystore_order_id` |
| `name` / `order_number` / `ref_number` | `hs_order_name` |
| `currency` / `currency_code` | `hs_currency_code` |
| store domain | `hs_source_store` |
| `fulfillment_status_label` / `fulfillment_status` | `hs_fulfillment_status` |
| shipping address street | `hs_shipping_address_street` |
| shipping address city | `hs_shipping_address_city` |
| shipping address zip/postal code | `hs_shipping_address_postal_code` |
| fulfillment tracking number | `hs_shipping_tracking_number` |
| fulfillment tracking URL | `hs_shipping_status_url` |

### Product-backed line items

Before any order/line-item writes, the order stage validates every EasyStore order line against the HubSpot Product library. A line must resolve by its real SKU, or by the same deterministic `ES-<product_id>-<variant_id>` key used by the product sync for SKU-less variants.

If an order line cannot resolve to a HubSpot Product, the order stage fails instead of silently creating a standalone line item. This guarantees every synchronized EasyStore merchandise line is product-backed.

Within an order, existing HubSpot Line Items are matched by `hs_sku`. Reruns update quantity, price, name and currency rather than creating duplicates. If an existing line is backed by the wrong HubSpot Product ID, it is recreated and re-associated to the Order using the correct product backing.

The HubSpot Line Item fields synchronized are:

| EasyStore order line | HubSpot Line Item |
| --- | --- |
| title/name/product name | `name` |
| SKU / synthetic SKU | `hs_sku` |
| matching HubSpot Product ID | `hs_product_id` |
| quantity | `quantity` |
| unit price | `price` |
| order currency | `hs_line_item_currency_code` |

If EasyStore repeats the same SKU more than once in one order at the same unit price, quantities are combined into one HubSpot Line Item for that product. Repeated SKU lines with different unit prices fail rather than being merged ambiguously.

### Order-to-contact matching

The order stage resolves the buyer using the same normalized-mobile rule as the customer sync. It checks customer data first and falls back to billing/shipping phone fields. A unique HubSpot Contact match is associated to the Order. Missing mobile numbers or ambiguous duplicate HubSpot contacts are counted and skipped rather than attaching the purchase to the wrong person.

## API behavior

EasyStore orders are paged from `/api/3.0/orders.json`. If a list record does not include `line_items`, the sync retrieves `/api/3.0/orders/<order_id>.json` before processing it.

HTTP 429 and 5xx responses are retried with bounded backoff. A remote API error fails the run. The order stage validates all EasyStore order lines against HubSpot Products before it starts writing orders or line items, preventing partially imported orders caused by missing catalog identity.

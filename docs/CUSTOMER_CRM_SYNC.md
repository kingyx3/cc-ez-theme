# EasyStore CRM sync

`.github/workflows/sync-easystore-customers-hubspot.yml` independently syncs EasyStore commerce/CRM data into HubSpot at **00:00, 06:00, 12:00 and 18:00 Singapore time** and can also be run manually with `workflow_dispatch`.

The current workflow syncs **Products first, then Customers**. Keeping the product library current first establishes the catalog identity that order line items can reference when order synchronization is added.

## Required repository secrets

- `EASYSTORE_ACCESS_TOKEN` — an EasyStore Public API access token with `read_products` and `read_customers` scopes. Add `read_orders` when order synchronization is enabled.
- `HUBSPOT_ACCESS_TOKEN` — a HubSpot access token with:
  - `crm.objects.products.read`
  - `crm.objects.products.write`
  - `crm.objects.contacts.read`
  - `crm.objects.contacts.write`
  - add `crm.objects.orders.read`, `crm.objects.orders.write`, `crm.objects.line_items.read`, and `crm.objects.line_items.write` when order synchronization is enabled.

The existing `EASYSTORE_ADMIN_TOKEN` used by theme deployment is intentionally not reused. EasyStore's documented Public API authenticates with the `EasyStore-Access-Token` header, so this sync has its own least-privilege read credential.

## Products and variants

`scripts/easystore_hubspot_products.py` synchronizes the EasyStore catalog into HubSpot's native Product library.

An **EasyStore variant maps to one HubSpot Product record**. This is deliberate: an EasyStore parent product can have multiple variants with separate SKUs and prices, while a HubSpot Product represents one SKU/unit-price combination. It also means an eventual EasyStore order line can reference the exact HubSpot Product record for the purchased variant.

Product identity is HubSpot `hs_sku`:

- if the EasyStore variant has a SKU, that value is used;
- if the EasyStore variant has no SKU, the sync generates the stable value `ES-<product_id>-<variant_id>`;
- if EasyStore contains duplicate non-blank SKUs, or HubSpot already contains multiple Products with the same SKU, the sync stops before writing products rather than guessing which record owns the SKU.

Fields currently synchronized are:

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

If multiple EasyStore customer records share a normalized mobile number, the most recently updated record wins for that run. If multiple HubSpot contacts already share the same normalized number, the sync does not guess: it leaves those contacts unchanged, reports the conflicting IDs and fails the run so the duplicate can be reconciled safely.

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

## Order model

When order synchronization is enabled, the intended model is:

1. **EasyStore Customer → HubSpot Contact**, keyed by normalized mobile number.
2. **EasyStore Variant → HubSpot Product**, keyed by SKU.
3. **EasyStore Order → HubSpot Order**, keyed by the immutable EasyStore order ID.
4. **EasyStore order item → HubSpot Line Item**, created from the corresponding HubSpot Product and associated to the HubSpot Order.
5. **HubSpot Order → Contact** association, so purchase history appears against the customer.

Products themselves are not associated directly to Orders in HubSpot; the product-backed Line Item is the transaction-specific instance that joins catalog data to an order.

## API behavior

HTTP 429 and 5xx responses are retried with bounded backoff. A remote API error fails the run. Customers without a usable mobile number are skipped and counted in the run summary. Product SKU ambiguity fails before any product batch is written so a bad identifier cannot silently merge catalog records.

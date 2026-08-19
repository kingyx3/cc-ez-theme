# EasyStore CRM sync

`.github/workflows/sync-easystore-customers-hubspot.yml` independently synchronizes EasyStore commerce/CRM data into HubSpot at **00:00, 06:00, 12:00 and 18:00 Singapore time** and can also be run manually with `workflow_dispatch`.

The production workflow runs in dependency order: **identity preflight → Products → Customers → Orders + Line Items → reconciliation**. Pull requests run only the credential-free validation job; they never call EasyStore or HubSpot with production credentials.

> GitHub Actions schedules are best-effort rather than a real-time scheduler. The workflow is configured for the four requested Singapore clock times, but GitHub may start scheduled runs late during platform load. Concurrency prevents two production sync runs from overlapping.

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
  - `crm.schemas.orders.read`
  - `crm.schemas.orders.write`

Optional repository variable `CUSTOMER_SYNC_DEFAULT_DIAL_CODE` defaults to Singapore `65`.

The existing `EASYSTORE_ADMIN_TOKEN` used by theme deployment is intentionally not reused. EasyStore's Public API uses the `EasyStore-Access-Token` header, so the CRM sync has its own least-privilege read credential.

## Production safety model

The integration is deliberately fail-closed where an automatic choice could merge the wrong identity or catalog record:

- **Customer identity preflight is read-only.** Before any Product, Contact, Order, or Line Item write, `scripts/easystore_hubspot_preflight.py` scans EasyStore customers and the relevant HubSpot Contacts. If more than one EasyStore customer owns the same normalized mobile, or an EasyStore mobile already maps to multiple HubSpot Contacts, the entire run stops before writes.
- **Product SKU ambiguity stops the Product stage before writes.** Duplicate EasyStore SKUs or multiple HubSpot Products with the same SKU are not guessed through.
- **Orders validate catalog references before order writes.** Every EasyStore merchandise line must resolve to a HubSpot Product before the order stage starts mutating Orders or Line Items.
- **HubSpot batch writes reject partial success.** Product and Contact batches send `objectWriteTraceId` values and require a `COMPLETE` response, zero item errors, and one returned result per submitted input. A successful HTTP status alone is not treated as a successful sync.
- **Stale synchronized order lines are reconciled only after the upsert succeeds.** `scripts/easystore_hubspot_reconcile.py` builds a complete reconciliation plan first, then archives product-backed HubSpot Line Items that no longer exist on their EasyStore order. Standalone/manual HubSpot line items without `hs_product_id` are preserved.
- **Transient remote failures retry.** HTTP 429 and 5xx responses use bounded backoff; persistent API errors fail the run and surface in Actions.
- **Production runs never overlap.** The workflow concurrency group serializes scheduled/manual production executions.

## Pull-request CI

Changes to the CRM workflow, sync scripts, CRM tests, or this document trigger the `Validate CRM sync` job on pull requests. That job requires no secrets and performs:

1. Python 3.13 bytecode compilation of every CRM sync script.
2. `crm_tests/test_crm_sync.py`, covering mobile normalization, duplicate-identity detection, SKU fallback, product-backed line construction, fail-closed catalog matching, stale-line reconciliation, order field mapping, and HubSpot partial-batch error handling.

The credentialed `sync` job is explicitly skipped for `pull_request` events.

This job is the coverage gate for the CRM sync scripts. `.coveragerc` omits `scripts/easystore_hubspot_*.py` from the theme suite's 100% line-and-branch requirement, because `tests/` exercises the theme packaging and validation tooling and never imports the CRM scripts. Adding a CRM script to `scripts/` therefore does not silently lower the theme gate, and the CRM scripts stay gated by compilation plus `crm_tests/` here.

The repository's browser E2E workflow is also a PR gate. Browser-installing jobs use timeout budgets that leave headroom for Playwright's network-bound browser/dependency installation so the actual regression tests are not cancelled before they execute. Each `playwright install --with-deps` invocation is additionally bounded and retried once: the flag shells out to `apt-get`, and a stalled Ubuntu mirror would otherwise consume the whole job budget and report the check as cancelled instead of failing.

## Products and variants

`scripts/easystore_hubspot_products.py` synchronizes the EasyStore catalog into HubSpot's native Product library.

An **EasyStore variant maps to one HubSpot Product record**. An EasyStore parent can have variants with separate SKUs and prices, while a HubSpot Product represents one catalog SKU/unit-price combination. Variant-level records also let each order line reference the exact purchased Product.

Product identity is HubSpot `hs_sku`:

- if the EasyStore variant has a SKU, that value is used;
- if the EasyStore variant has no SKU, the sync generates the stable value `ES-<product_id>-<variant_id>`;
- duplicate EasyStore SKUs or duplicate HubSpot Product SKUs stop the stage rather than choosing an owner.

Fields synchronized are:

| EasyStore | HubSpot Product |
| --- | --- |
| parent `title` + variant `name` | `name` |
| variant `sku` | `hs_sku` |
| variant `price` | `price` |
| parent `description` / `body_html` | `description` |
| variant `cost_price` | `hs_cost_of_goods_sold` |

EasyStore products are paged from `/api/3.0/products.json`. If a product-list response does not include variants, the sync retrieves `/api/3.0/products/<product_id>/variants.json`. HubSpot Products are scanned in pages and then created/updated through batch endpoints.

The sync intentionally does **not** delete HubSpot Products that disappear from the current EasyStore catalog, because historical Orders and Line Items may still refer to those products.

## Customer identity and normalization

The normalized mobile number is the only CRM Contact identity key. Email is synchronized as contact data but is never used to decide which HubSpot record belongs to an EasyStore customer.

`scripts/easystore_hubspot_sync.py` normalizes EasyStore `phone` values to a conservative E.164-style `+<country code><subscriber>` value. It uses the customer's EasyStore ISO `country_code` when available and otherwise falls back to `CUSTOMER_SYNC_DEFAULT_DIAL_CODE`.

The normalized value is written to both HubSpot `mobilephone` and `phone`. Existing HubSpot Contacts are normalized with the same function before matching, so formatting differences do not create a second Contact.

Duplicate ownership is **not** resolved by "latest record wins" in production. The preflight stops the entire run before writes when two distinct EasyStore customer IDs normalize to the same mobile or when one EasyStore mobile maps to multiple HubSpot Contacts. Those duplicates must be reconciled deliberately because mobile number is the authoritative identity.

Customers without a usable mobile number are skipped and counted; they cannot be safely assigned a CRM identity under this model.

## Customer fields synchronized

The Contact sync uses HubSpot standard properties only:

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

HubSpot email uniqueness is respected without turning email into identity. If an EasyStore email is already owned by a different HubSpot Contact, the phone-identified Contact is still synchronized but that conflicting email value is omitted and logged.

## Orders and product-backed line items

`scripts/easystore_hubspot_orders.py` runs only after Product and Contact synchronization succeeds.

The commerce model is:

1. **EasyStore Customer → HubSpot Contact**, keyed by normalized mobile number.
2. **EasyStore Variant → HubSpot Product**, keyed by SKU.
3. **EasyStore Order → HubSpot Order**, keyed by immutable EasyStore order ID.
4. **EasyStore order item → HubSpot Line Item**, backed by the matching Product through `hs_product_id`.
5. **HubSpot Order → Contact** association.
6. **HubSpot Order → Line Item** association.

Products themselves are catalog records; the product-backed Line Item is the transaction-specific instance joining the catalog to an Order.

### Order identity and idempotency

On the first production order-sync run, the script creates a HubSpot Order property group named `easystore_sync` and a unique text property named `easystore_order_id`. The immutable EasyStore order ID is stored there and used to resolve the same HubSpot Order on later runs.

If the property already exists but is not configured as unique, the sync stops rather than creating ambiguous order identity.

Order fields currently mapped include:

| EasyStore | HubSpot Order |
| --- | --- |
| `id` | custom unique `easystore_order_id` |
| `name` / `order_number` / `ref_number` | `hs_order_name` |
| `currency` / `currency_code` | `hs_currency_code` |
| store domain | `hs_source_store` |
| fulfillment status | `hs_fulfillment_status` |
| shipping address street | `hs_shipping_address_street` |
| shipping address city | `hs_shipping_address_city` |
| shipping address zip/postal code | `hs_shipping_address_postal_code` |
| fulfillment tracking number | `hs_shipping_tracking_number` |
| fulfillment tracking URL | `hs_shipping_status_url` |

### Product-backed line items

A line must resolve by its real SKU, or by the same deterministic `ES-<product_id>-<variant_id>` key used for SKU-less variants. If it cannot resolve to a HubSpot Product, the order stage fails instead of creating a standalone line item.

Within an Order, HubSpot Line Items are matched by `hs_sku`. Reruns update quantity, price, name, and currency rather than creating duplicates. If an existing synchronized line points at the wrong Product ID, it is recreated with the correct product backing.

Fields synchronized are:

| EasyStore order line | HubSpot Line Item |
| --- | --- |
| title/name/product name | `name` |
| SKU / synthetic SKU | `hs_sku` |
| matching HubSpot Product ID | `hs_product_id` |
| quantity | `quantity` |
| unit price | `price` |
| order currency | `hs_line_item_currency_code` |

If EasyStore repeats the same SKU in one Order at the same unit price, quantities are combined. Repeated SKU lines with different unit prices fail instead of being merged ambiguously.

After the main order upsert, reconciliation archives synchronized product-backed lines whose SKU has been removed from the EasyStore Order. Manual/standalone HubSpot line items are not archived by this integration.

### Order-to-contact matching

The buyer is resolved with the same normalized-mobile rule as Customer synchronization, checking customer data first and then billing/shipping phone fields. Because the workflow preflight has already ruled out duplicate CRM ownership, a unique Contact can be associated safely. Orders without a usable mobile remain unassociated and are counted in the run summary.

## API behavior

EasyStore orders are paged from `/api/3.0/orders.json`. If a list record does not include `line_items`, the sync retrieves `/api/3.0/orders/<order_id>.json` before processing it.

All product references are validated before order/line-item writes, and the stale-line archive plan is fully built before any archive request is sent. This reduces the blast radius of incomplete source reads or catalog mismatches.

HubSpot Product and Contact batch responses are inspected at the item level. The sync fails if HubSpot reports `numErrors`, returns an `errors` array, returns a non-`COMPLETE` batch status, or returns fewer/more result objects than inputs. Each submitted batch input carries an `objectWriteTraceId` so any HubSpot item-level error is attributable to a specific write.

## First-production-run checklist

Before merging/enabling the scheduled sync:

1. Configure `EASYSTORE_ACCESS_TOKEN` and `HUBSPOT_ACCESS_TOKEN` with exactly the scopes above.
2. Confirm `CUSTOMER_SYNC_DEFAULT_DIAL_CODE` if the store's default is not Singapore.
3. Reconcile any known duplicate customer mobile numbers in EasyStore or HubSpot; otherwise preflight will intentionally fail.
4. Prefer a manual run first and review all five Actions summary sections: Preflight, Products, Customers, Orders and Line Items, Reconciliation.
5. Spot-check several HubSpot Contacts, Products, Orders, and associated Line Items against EasyStore, including a multi-variant product and an order with more than one line.
6. For a full sandbox rehearsal before production, EasyStore supports development stores populated with Products, Variants, Customers, and Orders.

A green pull-request validation proves the deterministic mapping and fail-closed logic without credentials. A real API smoke test is still required to validate the specific EasyStore/HubSpot account configuration, scopes, existing CRM schema, and live data shape.
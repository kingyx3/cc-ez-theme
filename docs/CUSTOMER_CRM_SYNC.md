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

  Optional, for the extra EasyStore customer facts and catalogue detail below:

  - `crm.schemas.contacts.read`
  - `crm.schemas.contacts.write`
  - `crm.schemas.products.read`
  - `crm.schemas.line_items.read`

  Those stages degrade rather than fail: without the scopes, the Contact, Product
  and Line Item mappings log which extra fields they skipped and carry on
  synchronizing everything that uses standard HubSpot properties.

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

CI is bifurcated between this repository's two independent products. A pull request that only touches CRM sync sources runs the CRM gate and no theme jobs; a pull request that only touches the theme runs the theme jobs and not this one:

| Change | Workflow gate |
| --- | --- |
| `scripts/easystore_hubspot_*.py`, `crm_tests/**`, `docs/CUSTOMER_CRM_SYNC.md`, the CRM workflow | `Validate CRM sync` |
| `theme/**`, `tests/**`, `scripts/theme_ci.py`, `scripts/easystore_publish.py`, `requirements-dev.txt`, `.coveragerc`, the packaging workflow | `Package EasyStore theme` (push) |
| `theme/**`, `e2e/**`, `package.json`, `playwright.config.js`, the E2E workflow | `EasyStore browser E2E` (pull request) |

A change that spans both products triggers both sets of gates, and either workflow can still be started by hand with `workflow_dispatch`.

Changes to the CRM workflow, sync scripts, CRM tests, or this document trigger the `Validate CRM sync` job on pull requests. That job requires no secrets and performs:

1. Python 3.13 bytecode compilation of every CRM sync script, including the shared `easystore_hubspot_schema.py` property resolver.
2. `crm_tests/test_crm_sync.py`, covering mobile normalization, the no-mobile contact filter, duplicate-identity detection, SKU fallback, product-backed line construction, fail-closed catalog matching, stale-line reconciliation, order field mapping, order commerce-field resolution and provisioning, timestamp and amount normalization, lifecycle-stage transitions, and HubSpot partial-batch error handling.

The credentialed `sync` job is explicitly skipped for `pull_request` events.

This job is the coverage gate for the CRM sync scripts. `.coveragerc` omits `scripts/easystore_hubspot_*.py` from the theme suite's 100% line-and-branch requirement, because `tests/` exercises the theme packaging and validation tooling and never imports the CRM scripts. Adding a CRM script to `scripts/` therefore does not silently lower the theme gate, and the CRM scripts stay gated by compilation plus `crm_tests/` here.

The repository's browser E2E workflow is the PR gate for theme changes; it does not run for a CRM-only pull request, because no CRM change can alter the storefront it drives. Its browser-installing jobs use timeout budgets that leave headroom for Playwright's network-bound browser/dependency installation so the actual regression tests are not cancelled before they execute. Each `playwright install --with-deps` invocation is additionally bounded and retried once: the flag shells out to `apt-get`, and a stalled Ubuntu mirror would otherwise consume the whole job budget and report the check as cancelled instead of failing.

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

Catalogue detail is synchronized onto native HubSpot Product properties when the
portal has them, so the product card renders as HubSpot expects:

| EasyStore | HubSpot Product |
| --- | --- |
| `url` / `permalink` / `online_store_url` / `link`, else `handle` + store domain | `hs_url` |
| `image.src`, `images[].src/url`, `image_url`, `featured_image`, `thumbnail` | `hs_images` |
| `product_type` / `type` / `category_name` | `hs_product_type` |

These are native-only and optional: they need `crm.schemas.products.read` to
resolve, and a portal without the property simply stores nothing extra.
`easystore_catalogue_field_coverage` reports how many variants carried each one.

EasyStore products are paged from `/api/3.0/products.json`. If a product-list response does not include variants, the sync retrieves `/api/3.0/products/<product_id>/variants.json`. HubSpot Products are scanned in pages and then created/updated through batch endpoints.

The sync intentionally does **not** delete HubSpot Products that disappear from the current EasyStore catalog, because historical Orders and Line Items may still refer to those products.

## Customer identity and normalization

The normalized mobile number is the only CRM Contact identity key. Email is synchronized as contact data but is never used to decide which HubSpot record belongs to an EasyStore customer.

`scripts/easystore_hubspot_sync.py` normalizes EasyStore `phone` values to a conservative E.164-style `+<country code><subscriber>` value. It uses the customer's EasyStore ISO `country_code` when available and otherwise falls back to `CUSTOMER_SYNC_DEFAULT_DIAL_CODE`.

The normalized value is written to both HubSpot `mobilephone` and `phone`. Existing HubSpot Contacts are normalized with the same function before matching, so formatting differences do not create a second Contact.

Duplicate ownership is **not** resolved by "latest record wins" in production. The preflight stops the entire run before writes when two distinct EasyStore customer IDs normalize to the same mobile or when one EasyStore mobile maps to multiple HubSpot Contacts. Those duplicates must be reconciled deliberately because mobile number is the authoritative identity.

Contacts with no mobile number recorded are filtered out before any HubSpot write and counted as `skipped_without_mobile`; they cannot be safely assigned a CRM identity under this model. "Not recorded" covers a blank or missing `phone`, a value with no digits at all (`-`, `n/a`), a value too short or too long to be a real number, and placeholder values whose digits are all the same character (`0000000`, `1111111111`). `easystore_hubspot_sync.customer_mobile` is the single definition of this filter, and the preflight applies the same function, so an excluded contact cannot register as a duplicate-identity conflict either.

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

### Extra EasyStore customer facts

HubSpot's standard contact properties have no home for a storefront's own
customer record, and HubSpot's nearest equivalents (`total_revenue`,
`num_associated_deals`) are calculated from HubSpot records rather than writable.
These are therefore provisioned in the `easystore_sync` group:

| EasyStore | HubSpot Contact |
| --- | --- |
| `id` / `customer_id` | `easystore_customer_id` |
| `created_at` / `created_on` / `registered_at` | `easystore_customer_since` |
| `orders_count` / `order_count` / `total_orders` | `easystore_orders_count` |
| `total_spent` / `total_spend` / `lifetime_spend` | `easystore_total_spent` |
| `last_order_at` / `last_order_date` / `latest_order_at` | `easystore_last_order_at` |
| `birthday` / `birth_date` / `date_of_birth` / `dob` | `date_of_birth` or `easystore_customer_birthday` |
| `gender` / `sex` | `gender` or `easystore_customer_gender` |
| `tags` | `easystore_customer_tags` |
| `note` / `notes` / `remark` | `easystore_customer_note` |

Tags are normalized from a list, a comma separated string, or a list of objects
into one comma separated value. A birthday is stored as a HubSpot date, which
holds a day rather than an instant, so it is truncated to UTC midnight; a value
that does not parse as a date is dropped rather than rounded to today.
`easystore_customer_field_coverage` in the run summary reports how many
synchronized customers carried each fact.

### Merchant-defined customer attributes

A store's own customer questions — "How did you find us?" and anything else
defined in EasyStore — are synchronized without being named in this repository.
The Contact stage reads them from whichever collection EasyStore uses
(`custom_fields`, `customer_attributes`, `attributes`, `note_attributes`,
`metafields`, `fields`), in either the mapping shape (`{label: answer}`) or the
record shape (`{"label": ..., "value": ...}`), and a multi-answer value is joined
into one comma separated string.

Each distinct label becomes its own HubSpot property named
`easystore_attr_<slug>` with the original label as its HubSpot label, provisioned
on first sight:

| EasyStore attribute label | HubSpot Contact property |
| --- | --- |
| How did you find us? | `easystore_attr_how_did_you_find_us` |
| Favourite set | `easystore_attr_favourite_set` |

Because the set of attributes is a property of the store's data rather than of
this script, it is discovered from the customers that will actually be written
and resolved once per run, after the customer scan. Two guardrails keep a long
tail of one-off attributes from cluttering the CRM: labels are taken in
alphabetical order up to 25 per run, and two labels that would collide on one
property name keep the first. Anything left out is named in the step log rather
than dropped silently, and `easystore_customer_attributes_found` reports how many
distinct labels the run saw.

Birthday, gender and free-form attribute answers are personal data the store
already holds. They are copied as EasyStore recorded them, without inference: the
sync never derives a birthday from an order date or a gender from a name.

Marketing consent is deliberately **not** copied. A subscription state belongs to
the system that captured it, and re-deriving it from a storefront flag is exactly
the kind of quiet consent laundering a CRM should not do.

### Lifecycle stage

The CRM sync also maintains the contact's `lifecyclestage`:

- an EasyStore **account** makes the contact a `lead`, assigned by the customer sync;
- an EasyStore **order** makes its buyer a `customer`, assigned by the order sync once the order resolves to exactly one HubSpot Contact.

HubSpot does not move a contact backwards through the default lifecycle pipeline, so a stage is only written when it is a genuine step forward:

- a contact already at or beyond the target stage keeps the stage it reached — a later customer-sync run never demotes a buyer from `customer` back to `lead`;
- a stage outside HubSpot's default pipeline (`subscriber`, `lead`, `marketingqualifiedlead`, `salesqualifiedlead`, `opportunity`, `customer`, `evangelist`) belongs to a custom pipeline and is left untouched;
- an order whose buyer is ambiguous or has no usable mobile promotes nobody, exactly as it associates nobody.

The customer run summary reports `lifecycle_stage_leads_assigned` and the order run summary reports `contacts_promoted_to_customer`.

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
| order created timestamp | `hs_order_date` or `easystore_order_created_at` |
| payment status | `hs_payment_status` or `easystore_payment_status` |
| shipping/fulfilment status | `hs_fulfillment_status` or `easystore_fulfillment_status` |
| order total amount | `hs_total_price` or `easystore_total_amount` |
| merchandise subtotal | `hs_subtotal_price` / `hs_subtotal` or `easystore_subtotal_amount` |
| tax | `hs_tax` / `hs_tax_amount` / `hs_total_tax` or `easystore_tax_amount` |
| shipping charge | `hs_shipping_cost` / `hs_shipping_amount` / `hs_shipping_price` / `hs_total_shipping` or `easystore_shipping_amount` |
| order discount amount | `hs_order_discount_amount` / `hs_discount_amount` / `hs_total_discount` or `easystore_discount_amount` |
| discount codes | `easystore_discount_codes` |
| refunded amount | `easystore_refund_amount` |
| payment method | `hs_payment_method` or `easystore_payment_method` |
| order status | `hs_order_status` or `easystore_order_status` |
| paid / fulfilled / cancelled timestamps | `easystore_order_paid_at`, `easystore_order_fulfilled_at`, `easystore_order_cancelled_at` |
| cancellation reason | `easystore_order_cancel_reason` |
| sales channel | `easystore_order_channel` |
| units on the order | `easystore_order_item_count` |
| order tags | `easystore_order_tags` |
| buyer email / name / mobile | `easystore_order_email`, `easystore_order_customer_name`, `easystore_order_phone` |
| order note | `easystore_order_note` |
| shipping recipient / phone | `easystore_shipping_recipient`, `easystore_shipping_phone` |
| shipping method | `hs_shipping_method` |
| shipping address street/city/state/postal code/country | `hs_shipping_address_street` / `_city` / `_state` / `_postal_code` / `_country` |
| billing address street/city/state/postal code/country | `hs_billing_address_street` / `_city` / `_state` / `_postal_code` / `_country` |
| fulfillment tracking number | `hs_shipping_tracking_number` |
| fulfillment tracking URL | `hs_shipping_status_url` |

Each value is read from the first EasyStore field that carries it, so label and
raw variants are both handled:

| Field | EasyStore source, in order of preference |
| --- | --- |
| order created timestamp | `created_at`, `created_on`, `processed_at`, `order_date`, `date` |
| payment status | `payment_status_label`, `payment_status`, `financial_status_label`, `financial_status` |
| shipping/fulfilment status | `fulfillment_status_label`, `fulfillment_status`, `shipment_status`, `shipping_status` |
| total amount | `total_price`, `total_amount`, `grand_total`, `total` |
| merchandise subtotal | `subtotal_price`, `subtotal`, `sub_total`, `total_line_items_price` |
| tax | `total_tax`, `total_taxes`, `tax_total`, `tax_amount`, `tax` |
| shipping charge | `total_shipping`, `total_shipping_price`, `shipping_price`, `shipping_total`, `shipping_fee`, `shipping_amount`, `shipping_cost` |
| discount amount | `total_discount`, `total_discounts`, `discount_amount`, `discount_total` |
| discount codes | `discount_codes[].code`, then `discount_code` / `coupon_code` / `voucher_code` |
| refunded amount | `total_refunded`, `refunded_amount`, `refund_amount`, `total_refund` |
| payment method | `payment_method`, `payment_method_name`, `payment_gateway`, `gateway`, `payment_type` |
| order status | `status`, `order_status`, `state` |
| paid timestamp | `paid_at`, `payment_date`, `paid_on` |
| fulfilled timestamp | `fulfilled_at`, `shipped_at`, `fulfillment_date` |
| cancelled timestamp | `cancelled_at`, `canceled_at`, `cancellation_date` |
| cancellation reason | `cancel_reason`, `cancellation_reason`, `cancelled_reason` |
| sales channel | `source_name`, `sales_channel`, `channel`, `source` |
| units on the order | `item_count`, `total_items`, `line_items_count`, else the sum of line item quantities |
| order tags | `tags` (list, comma string, or list of objects) |
| buyer email | `customer.email`, then order `email` / `customer_email` / `contact_email`, then an address `email` |
| buyer name | `customer` name fields, then `customer_name` / `contact_name` / `buyer_name`, then an address name — never the order's own `name`, which is the order number |
| buyer mobile | the same normalized-mobile rule used to resolve the order's Contact |
| shipping recipient / phone | the delivery address `name` / `first_name` + `last_name`, and `phone` / `phone_number` / `mobile` |
| order note | `note`, `notes`, `customer_note`, `remark` |
| shipping method | `shipping_method`, `shipping_method_name`, `shipping_title`, `shipment_method`, `delivery_method`, then `shipping_lines[].title` |
| shipping address | `shipping_address`, else `billing_address`, else `address` |
| billing address | `billing_address` only |
| address street | `address1` + `address2` (`address_1`/`address_2`, `street`, `line1`/`line2`) |
| address state | `province`, `state`, `province_code`, `state_code` |
| address postal code | `zip`, `postal_code`, `postcode`, `post_code` |
| address country | `country`, `country_name`, `country_code` |

Buyer email, name and mobile are kept on the Order as well as on the Contact, so
a guest order that resolves to no Contact is still traceable to a person. An order
with no separate shipping address is still given one from its billing address,
because that is where the goods go. The billing fields stay strict, so
they are only filled from a real `billing_address`.

Because EasyStore's field names are the uncertain half of this mapping, every run
reports `easystore_order_field_coverage`: how many orders actually supplied each
field. A zero there means EasyStore did not send that fact under any of the names
above — not that HubSpot rejected it — which is the signal to add the real name to
the list. `hubspot_order_field_properties` reports the property each field landed
in.

Timestamps are converted to the epoch milliseconds HubSpot datetime properties
expect. ISO 8601 values keep the offset EasyStore reports; a value with no offset
is read as UTC rather than guessed at, and an epoch value is scaled from seconds
to milliseconds when needed.

Amounts are normalized to a bare decimal for HubSpot number properties: currency
prefixes and thousands separators are stripped, a value with no parseable amount
is omitted rather than written as text, and the discount amount is written as a
positive magnitude whether EasyStore reports it as `12.00` or `-12.00`. Discount
codes are joined into one comma separated value, de-duplicated in source order.
A field EasyStore does not report for an order is left untouched in HubSpot
rather than being cleared.

### Portal-specific property resolution

HubSpot's native schema is not identical between portals: a property can be
absent, calculated from other records (an order total rolled up from its line
items, for example), read-only, or defined as an enumeration that would reject
EasyStore's free-form labels. `scripts/easystore_hubspot_schema.py` is the shared
resolver used by the Product, Contact and Order stages. Before any write, it
reads `GET /crm/v3/properties/<object>` and resolves each declared field:

1. the preferred native property is used when the portal has it as a writable
   property of the expected type (`string`, `number` or `datetime`);
2. otherwise a commerce fact uses an `easystore_*` property in the
   `easystore_sync` group, created on first run, so the value always lands
   somewhere;
3. a presentation field declared native-only — shipping/billing address
   components, shipping method, tracking, catalogue URL/image/type — is skipped
   instead, because a duplicate custom property adds CRM clutter without adding a
   usable card;
4. an existing `easystore_*` property of a conflicting type stops the stage
   instead of producing a rejected write.

Each stage prints its resolved mapping to the step log and reports it in the run
summary (`hubspot_order_field_properties`, `hubspot_contact_field_properties`,
`hubspot_catalogue_field_properties`), together with
`commerce_fields_on_easystore_properties` for the order stage. Fields the portal
cannot store at all are logged as a warning naming each one.

The Order object stage treats this as required, because order identity depends on
the same schema route. The Contact, Product and Line Item mappings treat it as
optional: a token without `crm.schemas.contacts.*`,
`crm.schemas.products.read` or `crm.schemas.line_items.read` logs the fields it
skipped and still synchronizes every standard property.

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
| line discount (`total_discount` / `discount` / `discount_amount`) | `discount` |
| line tax (`total_tax` / `tax` / `tax_amount`) | `tax` |
| variant/option label (`variant_title` / `variant_name` / `option_title` / `options_label`) | `description` |

The last three are native-only and optional: they need
`crm.schemas.line_items.read` to resolve, and a portal without the property
stores nothing extra. `hubspot_line_item_field_properties` in the run summary
reports where they landed.

If EasyStore repeats the same SKU in one Order at the same unit price, quantities are combined. Repeated SKU lines with different unit prices fail instead of being merged ambiguously.

After the main order upsert, reconciliation archives synchronized product-backed lines whose SKU has been removed from the EasyStore Order. Manual/standalone HubSpot line items are not archived by this integration.

### Order-to-contact matching

The buyer is resolved with the same normalized-mobile rule as Customer synchronization, checking customer data first and then billing/shipping phone fields. Because the workflow preflight has already ruled out duplicate CRM ownership, a unique Contact can be associated safely. That same unique Contact is promoted to the `customer` lifecycle stage. Orders without a usable mobile remain unassociated, promote nobody, and are counted in the run summary.

## API behavior

EasyStore orders are paged from `/api/3.0/orders.json`. That list record is thinner than the single-order record: it was already missing `line_items` for some orders, and it also omits addresses and totals. The order stage therefore fetches `/api/3.0/orders/<order_id>.json` whenever a listed order is missing line items, an address, or an order total, and reports how often it had to (`orders_fetched_in_detail`). The reconciliation stage only reads line items, so it opts out of that check and its request count is unchanged.

All product references are validated before order/line-item writes, and the stale-line archive plan is fully built before any archive request is sent. This reduces the blast radius of incomplete source reads or catalog mismatches.

HubSpot Product and Contact batch responses are inspected at the item level. The sync fails if HubSpot reports `numErrors`, returns an `errors` array, returns a non-`COMPLETE` batch status, or returns fewer/more result objects than inputs. Each submitted batch input carries an `objectWriteTraceId` so any HubSpot item-level error is attributable to a specific write.

## First-production-run checklist

Before merging/enabling the scheduled sync:

1. Configure `EASYSTORE_ACCESS_TOKEN` and `HUBSPOT_ACCESS_TOKEN` with exactly the scopes above.
2. Confirm `CUSTOMER_SYNC_DEFAULT_DIAL_CODE` if the store's default is not Singapore.
3. Reconcile any known duplicate customer mobile numbers in EasyStore or HubSpot; otherwise preflight will intentionally fail.
4. Prefer a manual run first and review all five Actions summary sections: Preflight, Products, Customers, Orders and Line Items, Reconciliation.
5. Spot-check several HubSpot Contacts, Products, Orders, and associated Line Items against EasyStore, including a multi-variant product and an order with more than one line.
6. Read the three coverage blocks in the run summary (`easystore_order_field_coverage`, `easystore_customer_field_coverage`, `easystore_catalogue_field_coverage`). Any field sitting at zero is one EasyStore does not report under the names the sync knows; add the real name to that field's `sources` and the value starts landing on the next run.
7. For a full sandbox rehearsal before production, EasyStore supports development stores populated with Products, Variants, Customers, and Orders.

A green pull-request validation proves the deterministic mapping and fail-closed logic without credentials. A real API smoke test is still required to validate the specific EasyStore/HubSpot account configuration, scopes, existing CRM schema, and live data shape.
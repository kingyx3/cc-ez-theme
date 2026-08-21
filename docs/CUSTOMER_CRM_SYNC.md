# EasyStore CRM sync

`.github/workflows/sync-easystore-customers-hubspot.yml` independently synchronizes EasyStore commerce/CRM data into HubSpot at **00:00, 06:00, 12:00 and 18:00 Singapore time** and can also be run manually with `workflow_dispatch`.

The production workflow runs in dependency order: **identity preflight → Products → Customers → Orders + Line Items → reconciliation → Abandoned checkouts → Cloudflare source attribution**. Abandoned checkouts run late on purpose: it is the only stage whose EasyStore route is undocumented, so a store that does not serve one cannot cost the run the stages above it. Source attribution runs last for the same kind of reason: it is the only stage that depends on a third system, and on provisioning HubSpot properties the other stages do not need. Pull requests run only the credential-free validation job; they never call EasyStore or HubSpot with production credentials.

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
  - `crm.objects.carts.read`
  - `crm.objects.carts.write`
  - `crm.schemas.carts.read`

  Those stages degrade rather than fail: without the scopes, the Contact, Product
  and Line Item mappings log which extra fields they skipped and carry on
  synchronizing everything that uses standard HubSpot properties, and the
  abandoned-checkout stage reports that the Cart object is unavailable and stops
  there.

Optional repository variable `CUSTOMER_SYNC_DEFAULT_DIAL_CODE` defaults to Singapore `65`.

The source-attribution stage additionally reads `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` - the same secrets the Worker deployment uses. It only ever reads D1, so a token scoped to D1 read on that one account is enough. Without them that single stage is skipped and the run continues. On the HubSpot side it is the one stage that *requires* `crm.schemas.contacts.read` and `crm.schemas.contacts.write`, because every property it writes is one it provisions.

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
| `scripts/easystore_hubspot_*.py`, `scripts/cloudflare_hubspot_attribution.py`, `crm_tests/**`, `docs/CUSTOMER_CRM_SYNC.md`, `docs/SOURCE_ATTRIBUTION.md`, the CRM workflow | `Validate CRM sync` |
| `cloudflare/attribution-worker/**`, the Worker workflow | `Validate Worker` (pull request), then deploy on `main` |
| `theme/**`, `tests/**`, `scripts/theme_ci.py`, `scripts/easystore_publish.py`, `requirements-dev.txt`, `.coveragerc`, the packaging workflow | `Package EasyStore theme` (push) |
| `theme/**`, `e2e/**`, `package.json`, `playwright.config.js`, the E2E workflow | `EasyStore browser E2E` (pull request) |

A change that spans both products triggers both sets of gates, and either workflow can still be started by hand with `workflow_dispatch`.

Changes to the CRM workflow, sync scripts, CRM tests, or this document trigger the `Validate CRM sync` job on pull requests. That job requires no secrets and performs:

1. Python 3.13 bytecode compilation of every CRM sync script, including the shared `easystore_hubspot_schema.py` property resolver and the abandoned-checkout stage.
2. `crm_tests/`, covering mobile normalization, the no-mobile contact filter, duplicate-identity detection, SKU fallback, product-backed line construction, fail-closed catalog matching, stale-line reconciliation, order field mapping, order commerce-field resolution and provisioning, timestamp and amount normalization, lifecycle-stage transitions, HubSpot partial-batch error handling, and the Cloudflare click join's click-id validation, contact paging, D1 reads and every refusal above.

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
| `product_type` / `type` / `category_name` / `category_title`, else a `category` / `categories` / `collection` / `collections` entry | `hs_product_type` |

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
| `birthdate`, then `birthday` / `birth_date` / `date_of_birth` / `dob` | `date_of_birth` or `easystore_customer_birthday`, plus `easystore_birthday_day` and `easystore_next_birthday` — see below |
| `gender` / `sex` | `gender` or `easystore_customer_gender` |
| `tags` | `easystore_customer_tags` |
| `note` / `notes` / `remark` / `remarks` / `internal_note` / `admin_note` / `staff_note` / `comment` / `comments` / `memo` / `description` | `easystore_customer_note` |

Tags are normalized from a list, a comma separated string, or a list of objects
into one comma separated value. `easystore_customer_field_coverage` in the run
summary reports how many synchronized customers carried each fact.

A note is read whether it arrives as a string, as a record holding the words, or
as a list of note records with their own timestamps; several notes are joined in
the order given. EasyStore calls a shopper's own order message a *remark* — the
storefront renders `order.remark` — so that wording is tried for a customer note
too, alongside the usual names.

**No container is ever written as text.** `str([])` is `"[]"`, and a list of note
records stringifies to a Python repr; either would have landed in the CRM as the
note. A value that arrives as a list or a mapping now reads as absent unless the
field has a derivation that knows its shape, which also means a money field
arriving as a nested object asks for the record's detail instead of writing
nonsense.

#### Birthdays

EasyStore keeps a real date of birth in **`birthdate`** — the field its own
storefront reads and writes, rendered by `theme/templates/customers/account.liquid`
as `<input type="date" value="{{customer.birthdate}}" max="today">` and locked
when `customer.birthdate_editable` is false. That is the field to read, and it is
read first.

**`birthday` is a different thing: it comes back as the next occurrence of that
date.** A January birthday read in August arrives dated next January, which is
why the first production run filled HubSpot with birthdays in 2027 — the sync was
reading `birthday` and never read `birthdate` at all. The year of a `birthday`
value says when the birthday next falls; only the day and month are real.

So the birthday is split into three properties, each holding only what is true:

| HubSpot Contact | Holds |
| --- | --- |
| `easystore_birthday_day` | the day and month as `MM-DD` — always trustworthy, and what a birthday campaign filters on |
| `easystore_next_birthday` | when the birthday next falls: EasyStore's own value when that is what it sent, or a real date of birth projected forward |
| `date_of_birth` or `easystore_customer_birthday` | a **real** date of birth, and only that |

A date within the last twelve months cannot be a date of birth — nobody with a
storefront account was born this week — so it is read as an occurrence. No birth
year is ever invented from one.

Because this sync provisions `easystore_customer_birthday`, it also owns it: when
no date of birth is reported, the property is cleared, which repairs the contacts
an earlier run filled with a next-occurrence date. `birthday_property_cleared`
reports how many were cleared. A portal whose **native** `date_of_birth` was
resolved instead is never cleared, because that property belongs to the portal
and a person may maintain it by hand.

Getting from a storefront's value to a HubSpot date had three further traps, all
of which produced wrong dates in production:

- **A date must keep the calendar day it was written with.** Converting an
  offset-bearing midnight (`1993-04-20T00:00:00+08:00`) to UTC first moved every
  birthday to the previous day for a store east of Greenwich.
- **A compact date is not an epoch.** `19930420` read as epoch seconds lands in
  August 1970. A four-digit year followed by a month and a day is now read as the
  date it plainly is.
- **Nobody is born in the future.** A future date is never written as a date of
  birth. With the occurrence rule above, such a value now has a correct home
  rather than simply being discarded.

Because the wrong value cannot be inspected from CI without putting someone's
date of birth in a build log, each run reports it redacted:
`easystore_birthday_shapes` gives the masked shape per source
(`birthday=####-##-##`), `easystore_birthday_years` gives the year each source
parses to as a distribution, and `birthdays_in_future_ignored` counts the values
refused as a date of birth. Between them, a wrong birthday is diagnosable without
disclosing one: a year distribution clustered on next year is the signature of
the occurrence behaviour above.

### Merchant-defined customer attributes

A store's own customer questions — "How did you find us?" and anything else
defined in EasyStore — are synchronized without being named in this repository.
The Contact stage reads them from whichever collection EasyStore uses
(`custom_fields`, `customer_attributes`, `attributes`, `note_attributes`,
`metafields`, `fields`), and a multi-answer value is joined into one comma
separated string.

**An EasyStore answer does not carry its question.** The storefront's own account
page shows the shape: `customer.attributes` holds
`{"customer_attribute_setting_id": 7, "value": "Instagram"}`, and the wording
lives separately in `shop.attribute_settings`, which the page matches against by
id. So the stage looks the wording up once per run — trying
`customer_attribute_settings.json`, `attribute_settings.json`,
`customer_attributes.json` and `shop.json`, and reporting the route that answers
as `easystore_attribute_setting_route`. An answer whose question cannot be named
is still synchronized, under its setting id (`easystore_attr_setting_7`), because
losing an answer is worse than an ugly property name. A mapping of question to
answer and a record carrying its own label are both read too.

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

## Cloudflare source attribution

`scripts/cloudflare_hubspot_attribution.py` runs **last** and answers the one
question the storefront's own data cannot: **which channel produced this
customer.**

Last, and not straight after Contacts where it first sat, because it is the only
stage that depends on a third system and on provisioning HubSpot properties the
other stages do not need. Sitting mid-run, a Cloudflare outage or a HubSpot token
without schema scopes would have taken the Orders, Line Items, Reconciliation and
Cart stages down with it — stages that have nothing to do with attribution. It
reads no EasyStore data at all, so nothing above it depends on it either.

Given no `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`, the workflow logs a
notice and skips it entirely.

**Its HubSpot scope requirement is stricter than the other stages'.** The
Contact, Product and Line Item mappings treat `crm.schemas.*` as optional and
degrade to standard properties without it. This stage cannot: every property it
writes is one it provisions, and without somewhere to store the acquisition click
id a rerun could not tell an already-attributed contact from a new one and would
rewrite the same contacts every six hours. So it needs
`crm.schemas.contacts.read` and `crm.schemas.contacts.write`, and it fails the
run rather than degrading if they are missing.

The chain it completes is documented in full in
[docs/SOURCE_ATTRIBUTION.md](SOURCE_ATTRIBUTION.md), including the one manual
EasyStore setup step and the limits of the claim. In brief: the `cc-attribution`
Cloudflare Worker mints an opaque `click_id` per tracked `/go/*` entry and records
the channel in D1; the storefront carries that id into an EasyStore customer
attribute at sign-up; the Contact stage above already copies customer attributes
to HubSpot, so the id arrives as `easystore_attr_click_id`; this stage resolves it
against D1 and writes the channel onto the contact.

Values land in a **Cloudflare Attribution** property group, deliberately separate
from `easystore_sync` so a CRM user can tell which system reported a fact:
`cc_acquisition_click_id`, `_source`, `_medium`, `_campaign`, `_entry_path`,
`_country`, `_at` and `_automated`. HubSpot's own `hs_analytics_source` family is
never written: those belong to HubSpot's tracking code and are enumerated against
HubSpot's channel list.

Four refusals define the stage:

- **An acquisition is written once.** A contact already carrying a different
  click id is reported as `contacts_with_conflicting_click_id` and left alone.
- **A click id with no D1 row writes nothing** (`click_ids_not_found_in_d1`).
- **A value that is not a Worker-minted UUID never reaches a query.** The
  attribute is filled by a script in a browser, so it is untrusted input and is
  counted as `contacts_with_unusable_click_id`.
- **Nothing to join provisions nothing.** With no click ids in the portal the
  stage creates no HubSpot properties and makes no Cloudflare call, which is the
  expected state until the EasyStore attribute exists.

`attributed_by_source` and `attributed_by_campaign` in the run summary are the
reporting output; `contacts_already_attributed` is the normal headline number of a
healthy scheduled run.

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
| order status | `status`, `order_status`, `order_status_label`, `status_label`, `state`, `order_state`, `state_label` |
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
| payment method | `payment_method`, `payment_method_name`, `payment_method_title`, `payment_gateway`, `gateway`, `payment_type`, `payment_name`, then `payment` / `payments` / `transactions` / `payment_details` entries |
| shipping method | `shipping_method`, `shipping_method_name`, `shipping_method_title`, `shipping_title`, `shipment_method`, `delivery_method`, `delivery_option`, `courier`, then `shipping_lines` / `shipment` / `shipments` entries |
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

Because EasyStore's field names and HubSpot's property names are the uncertain
halves of this mapping, every run reports what it saw so the next one can be
exact:

| Summary key | Answers |
| --- | --- |
| `easystore_order_field_coverage` | how many orders supplied each field — a zero means EasyStore did not send that fact under any name the sync knows, not that HubSpot rejected it |
| `easystore_order_keys_seen`, `easystore_order_address_keys_seen`, `easystore_line_item_keys_seen` | the field names EasyStore actually returns (names only, never values), which is where a zero above gets traced to the real name |
| `hubspot_order_field_properties` | the property each field landed in |
| `hubspot_order_property_hints` | for a field that found no native property: the portal's own properties whose name or label looks related, so a value sitting in an `easystore_*` property can be pointed at the native one |
| `orders_fetched_in_detail` | how many listed orders were too thin to map and had to be re-read |

The Contact and Product stages report the same three kinds of block
(`easystore_customer_keys_seen`, `hubspot_contact_property_hints`,
`easystore_product_keys_seen`, `hubspot_variant_keys_seen`,
`hubspot_product_property_hints`). The Order stage additionally prints the
portal's full Order property inventory to the step log.

The address is the case worth knowing about. EasyStore's order **list** returns a
stub address carrying only a country, which is present enough to look like an
address while saying nothing about where to deliver. A stub therefore does not
count as an address: an order needs its detail fetched whenever no address states
a street or a city, and a stub shipping address never hides a real billing
address. The stub's country still reaches HubSpot.

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

## Abandoned checkouts

`scripts/easystore_hubspot_carts.py` synchronizes EasyStore abandoned checkouts
into HubSpot's native **Cart** object, keyed by `hs_external_cart_id` holding the
EasyStore checkout ID. An abandoned checkout is CRM-worthy in its own right: it
names a contactable person, the value they were about to spend, and the link that
would let them finish.

**A completed checkout is not a cart.** It already exists as an Order, so copying
it here would double-count revenue. A checkout is treated as completed when it
references an order, carries a `completed_at`, or reports a status of completed,
complete, paid, converted or order; the run reports
`checkouts_skipped_as_completed`.

Fields synchronized are:

| EasyStore | HubSpot Cart |
| --- | --- |
| checkout `id` (or `token`) | `hs_external_cart_id` |
| `name` / `checkout_number` / `token` | `hs_cart_name` |
| store domain | `hs_source_store` |
| `currency` / `currency_code` | `hs_currency_code` |
| `status` / `state` / `checkout_status` | `hs_external_status` or `easystore_cart_status` |
| `total_price` / `total_amount` / `grand_total` / `total` | `hs_total_price` or `easystore_cart_total_amount` |
| `subtotal_price` / `subtotal` / `sub_total` / `total_line_items_price` | `hs_subtotal_price` or `easystore_cart_subtotal_amount` |
| `total_discount` / `total_discounts` / `discount_amount` | `hs_cart_discount` or `easystore_cart_discount_amount` |
| `total_tax` / `total_taxes` / `tax_total` / `tax` | `hs_tax` or `easystore_cart_tax_amount` |
| `total_shipping` / `shipping_price` / `shipping_total` / `shipping_fee` | `hs_shipping_cost` or `easystore_cart_shipping_amount` |
| `tags` | `hs_tags` or `easystore_cart_tags` |
| `created_at` / `created_on` / `started_at` | `hs_external_created_date` or `easystore_cart_created_at` |
| `abandoned_at` / `updated_at` / `last_activity_at` | `hs_external_modified_date` or `easystore_cart_abandoned_at` |
| `abandoned_checkout_url` / `recovery_url` / `checkout_url` | `hs_cart_url` or `easystore_cart_recovery_url` |
| `token` / `cart_token` / `checkout_token` | `hs_external_token` |
| `discount_codes` (or `discount_code` / `coupon_code` / `voucher_code`) | `hs_discount_codes` |
| `landing_site` / `landing_page` | `hs_landing_site` |
| `referring_site` / `referrer` | `hs_referring_site` |
| `total_weight` / `weight` | `hs_total_weight` (HubSpot types this one as text, so the unit travels with the number) |
| `shipping_address` (falling back to `billing_address`) | `hs_shipping_address_street`, `_city`, `_state`, `_postal_code`, `_country`, `_phone` |
| `billing_address` | `hs_billing_address_street`, `_city`, `_state`, `_postal_code`, `_country`, `_phone` |
| line item quantities | `easystore_cart_item_count` |
| line item titles and quantities | `easystore_cart_items` |
| shopper email / name / mobile | `easystore_cart_email`, `easystore_cart_customer_name`, `easystore_cart_phone` |

Everything from `token` down is **native-only**: HubSpot defines those on every
Cart object, so a portal that somehow lacks one gains nothing from a duplicate
custom property. `hs_buyer_accepts_marketing` exists on the Cart object and is
deliberately left alone — this sync never writes marketing consent.

The shopper is resolved to a Contact with the same normalized-mobile rule as
everything else, and associated using HubSpot's **v4 default association** route
rather than a hard-coded association type ID, which is not documented for carts
and would associate the wrong way if guessed.

Two things this stage refuses to guess:

- **Which EasyStore route serves abandoned checkouts.** `checkouts.json`,
  `abandoned_checkouts.json`, `carts.json` and `abandoned_carts.json` are each
  probed for a single record. The first route holding records is used for the
  whole run and reported as `easystore_checkout_route`; a route that answers
  empty is only settled for once no other route has anything, so an empty
  `checkouts.json` cannot mask a populated `abandoned_carts.json`. Every probe's
  outcome is reported as `easystore_checkout_route_probes`.

  **A probe never fails the run.** Discovery is not the sync: a candidate that
  404s, serves the storefront's HTML, or hangs until the read times out is
  recorded with that reason and passed over. This is what took run
  [32449737153](https://github.com/kingyx3/cc-ez-theme/actions/runs/32449737153)
  down — `checkouts.json` accepted the connection and never answered, and the
  timeout propagated out as a failed workflow. Probes now use one record, one
  retry and a 20-second read timeout, so proving four routes dead costs seconds
  rather than the twenty minutes the default retry policy would have spent.
- **Whether the portal has a Cart object at all.** Not every HubSpot account
  does. A portal without one reports `hubspot_cart_object: unavailable` and is
  skipped rather than inventing somewhere else to put the data.

### The customer list is thinner than the customer record

Like orders, EasyStore's customer *list* returns less than its customer
endpoint. The Contact stage therefore fetches `/api/3.0/customers/<id>.json`
whenever a listed customer is missing the birthday, attributes or note fields
altogether, and reports `customers_fetched_in_detail`.

Key presence is the test, not a value. A customer legitimately has no birthday
and no answers, so testing values would re-fetch those customers on every run
forever; a missing *key* is what says the list endpoint does not carry the field
at all.

## API behavior

EasyStore orders are paged from `/api/3.0/orders.json`. That list record is thinner than the single-order record: it was already missing `line_items` for some orders, and it also omits addresses and totals. The order stage therefore fetches `/api/3.0/orders/<order_id>.json` whenever a listed order is missing line items, an address, or an order total, and reports how often it had to (`orders_fetched_in_detail`). The reconciliation stage only reads line items, so it opts out of that check and its request count is unchanged.

All product references are validated before order/line-item writes, and the stale-line archive plan is fully built before any archive request is sent. This reduces the blast radius of incomplete source reads or catalog mismatches.

HubSpot Product and Contact batch responses are inspected at the item level. The sync fails if HubSpot reports `numErrors`, returns an `errors` array, returns a non-`COMPLETE` batch status, or returns fewer/more result objects than inputs. Each submitted batch input carries an `objectWriteTraceId` so any HubSpot item-level error is attributable to a specific write.

## First-production-run checklist

Before merging/enabling the scheduled sync:

1. Configure `EASYSTORE_ACCESS_TOKEN` and `HUBSPOT_ACCESS_TOKEN` with exactly the scopes above.
2. Confirm `CUSTOMER_SYNC_DEFAULT_DIAL_CODE` if the store's default is not Singapore.
3. Reconcile any known duplicate customer mobile numbers in EasyStore or HubSpot; otherwise preflight will intentionally fail.
4. Prefer a manual run first and review all seven Actions summary sections: Preflight, Products, Customers, Orders and Line Items, Reconciliation, Abandoned checkouts, Cloudflare source attribution.
5. Spot-check several HubSpot Contacts, Products, Orders, and associated Line Items against EasyStore, including a multi-variant product and an order with more than one line.
6. Read the three coverage blocks in the run summary (`easystore_order_field_coverage`, `easystore_customer_field_coverage`, `easystore_catalogue_field_coverage`). Any field sitting at zero is one EasyStore does not report under the names the sync knows; add the real name to that field's `sources` and the value starts landing on the next run.
7. For a full sandbox rehearsal before production, EasyStore supports development stores populated with Products, Variants, Customers, and Orders.

A green pull-request validation proves the deterministic mapping and fail-closed logic without credentials. A real API smoke test is still required to validate the specific EasyStore/HubSpot account configuration, scopes, existing CRM schema, and live data shape.
# EasyStore → HubSpot CRM field map

This document is the source of truth for which HubSpot properties the CRM sync
owns and writes. It exists so HubSpot lists, reports and workflows can distinguish
fields that are populated by this integration from fields that are not.

## Mapping rule: native first, custom only to prevent data loss

Every field with an EasyStore fallback is resolved against the live HubSpot
schema before a write.

1. A declared native HubSpot property is used when it exists, is writable and has
   the same storage type.
2. If that declared name is unavailable, the resolver may use another
   **HubSpot-defined** property only when exactly one writable property has the
   same semantic words and the exact same storage type.
3. An `easystore_*` property is created/used only when no unambiguous lossless
   native destination exists.
4. HubSpot enumerations are not force-fed EasyStore free-form text. If the
   EasyStore values cannot be mapped to the native option set without changing or
   dropping information, the custom fallback is kept.
5. Existing legacy `easystore_*` properties are not automatically archived or
   deleted when a native property becomes usable. They may contain historical
   data. New sync runs simply stop writing the fallback when the native property
   wins.

The one exception is identity data that has no HubSpot-native external ID for the
object. Those properties are intentionally custom because removing them would
break idempotent matching.

## Products

One EasyStore variant is one HubSpot Product. No custom Product properties are
created by this sync.

| EasyStore value | HubSpot Product property | Rule |
| --- | --- | --- |
| parent title + variant name | `name` | native |
| variant SKU, or synthetic `ES-<product>-<variant>` | `hs_sku` | native identity |
| variant/product price | `price` | native |
| parent description / `body_html` | `description` | native |
| variant `cost_price` | `hs_cost_of_goods_sold` | native |
| product URL / handle | `hs_url` | native-only when portal exposes it |
| product image | `hs_images` | native-only when portal exposes it |
| product type/category | `hs_product_type` | native-only when portal exposes it |
| `published_at` / explicit publication flag | native Product Status / active property | published → Active; unpublished → Inactive |

Product publication status is resolved from the live Product schema so the sync
uses the portal's actual Active/Inactive option values. `crm.schemas.products.read`
is required for this status mapping. If the native status property or option set
cannot be resolved losslessly, status is left unchanged rather than creating a
custom Product status.

A missing `published_at` key is not treated as unpublished. A present null/blank
`published_at` is unpublished; a timestamp is published. Inventory availability
is deliberately not used as a publication signal.

## Contacts

### Native Contact properties

| EasyStore value | HubSpot Contact property |
| --- | --- |
| normalized phone | `phone` (authoritative identity), `mobilephone` (mirror only) |
| `first_name` | `firstname` |
| `last_name` | `lastname` |
| `email` | `email` |
| primary address line 1/2 | `address` |
| primary address city | `city` |
| primary address province | `state` |
| primary address postcode | `zip` |
| primary address/customer country | `country` |
| primary address company | `company` |
| EasyStore-account lifecycle | `lifecyclestage` (`lead`; order stage may promote to `customer`) |
| birthday/date of birth | `date_of_birth` when writable and lossless |
| gender | `gender` when writable and lossless |

The normalized EasyStore number is still written to both native phone fields for
usability in HubSpot, but identity matching is deliberately narrower. Preflight
and the production Customer upsert use only HubSpot `phone` as the Contact
identity. A value present only in another Contact's `mobilephone` is not a
second owner of that identity and must not stop the sync. Two Contacts whose
primary `phone` values normalize to the same EasyStore number are still a real
ambiguity and fail closed before writes.

### Contact custom/fallback properties

These are created only when their row says there is no safe native equivalent, or
when the live portal has no writable lossless native property.

| Custom property | EasyStore fact | Why custom can be necessary |
| --- | --- | --- |
| `easystore_customer_id` | EasyStore customer ID | external store identity; no equivalent native Contact identity |
| `easystore_customer_since` | account creation timestamp | fallback when no writable native equivalent exists |
| `easystore_orders_count` | EasyStore order count | HubSpot's nearest aggregate fields are calculated from HubSpot records |
| `easystore_total_spent` | EasyStore lifetime spend | HubSpot revenue aggregates are calculated/read-only and are not the same source fact |
| `easystore_last_order_at` | latest EasyStore order timestamp | fallback when no writable native equivalent exists |
| `easystore_customer_birthday` | real date of birth | fallback only when native `date_of_birth` is unavailable/incompatible |
| `easystore_birthday_day` | trusted birthday `MM-DD` | no equivalent native field with the same meaning |
| `easystore_next_birthday` | next birthday occurrence | different semantic from date of birth |
| `easystore_customer_gender` | EasyStore gender | fallback only when native `gender` is unavailable/incompatible |
| `easystore_customer_tags` | EasyStore customer tags | fallback when no unambiguous writable native equivalent exists |
| `easystore_customer_note` | EasyStore staff/customer note | fallback when no unambiguous writable native equivalent exists |
| `easystore_attr_<slug>` | merchant-defined EasyStore customer attribute | merchant-defined source field; no generic HubSpot native equivalent |

Merchant-defined attributes are capped by the sync and use one property per
attribute label so answers are not merged into an unrelated CRM field.

## Orders

### Native Order properties always used directly

| EasyStore value | HubSpot Order property |
| --- | --- |
| order name/number | `hs_order_name` |
| store domain | `hs_source_store` |
| currency | `hs_currency_code` |
| shipping method | `hs_shipping_method` when present |
| tracking number | `hs_shipping_tracking_number` when present |
| tracking URL | `hs_shipping_status_url` when present |
| shipping address | `hs_shipping_address_*` fields when present |
| billing address | `hs_billing_address_*` fields when present |

### Order native-first fields with custom fallbacks

For these fields the custom property in the third column is used **only** when no
lossless native property can be selected. This includes type mismatches: for
example, a date-only native property does not replace an EasyStore timestamp if
that would discard the time of day.

| EasyStore fact | Preferred/native candidates | Custom fallback |
| --- | --- | --- |
| creation timestamp | `hs_order_date` / unique semantic native | `easystore_order_created_at` |
| payment status | `hs_payment_status` / unique semantic native | `easystore_payment_status` |
| fulfilment status | `hs_fulfillment_status` / unique semantic native | `easystore_fulfillment_status` |
| total | `hs_total_price` | `easystore_total_amount` |
| subtotal | `hs_subtotal_price`, `hs_subtotal` | `easystore_subtotal_amount` |
| tax | `hs_tax`, `hs_tax_amount`, `hs_total_tax` | `easystore_tax_amount` |
| shipping charge | HubSpot shipping amount/cost candidates | `easystore_shipping_amount` |
| order discount amount | HubSpot order/discount amount candidates | `easystore_discount_amount` |
| refund amount | unique semantic native if one exists | `easystore_refund_amount` |
| discount codes | unique semantic native if one exists | `easystore_discount_codes` |
| payment method | `hs_payment_method` / unique semantic native | `easystore_payment_method` |
| overall order status | `hs_order_status` / unique semantic native | `easystore_order_status` |
| paid timestamp | unique semantic native if one exists | `easystore_order_paid_at` |
| fulfilled timestamp | unique semantic native if one exists | `easystore_order_fulfilled_at` |
| cancelled timestamp | unique semantic native if one exists | `easystore_order_cancelled_at` |
| cancellation reason | unique semantic native if one exists | `easystore_order_cancel_reason` |
| sales channel | unique semantic native if one exists | `easystore_order_channel` |
| item/unit count | unique semantic native if one exists | `easystore_order_item_count` |
| tags | unique semantic native if one exists | `easystore_order_tags` |
| buyer email | unique semantic native if one exists | `easystore_order_email` |
| buyer name | unique semantic native if one exists | `easystore_order_customer_name` |
| buyer phone | unique semantic native if one exists | `easystore_order_phone` |
| shipping recipient | unique semantic native if one exists | `easystore_shipping_recipient` |
| shipping phone | unique semantic native if one exists | `easystore_shipping_phone` |
| order note | unique semantic native if one exists | `easystore_order_note` |

### Order identity custom property

`easystore_order_id` is always custom, unique, and required. It is the immutable
EasyStore order identity used to update the same HubSpot Order on later runs.
There is no HubSpot-native EasyStore external-order-ID field that can replace this
without changing the sync identity model.

## Line Items

The order Line Item sync creates no custom properties. Core and optional detail
use native HubSpot Line Item fields only.

| EasyStore value | HubSpot Line Item property |
| --- | --- |
| item title/name | `name` |
| SKU | `hs_sku` |
| associated HubSpot Product | `hs_product_id` |
| quantity | `quantity` |
| unit price | `price` |
| currency | `hs_line_item_currency_code` |
| line discount | `discount` when writable |
| line tax | `tax` when writable |
| variant/option label | `description` when writable |

If an optional native Line Item field is not available, that detail is skipped;
a custom duplicate is not created because HubSpot's own Order/Line Item editor is
authoritative for these fields.

## Carts / abandoned checkouts

`hs_external_cart_id` is the native Cart external identity. Native Cart fields are
preferred first for status, totals, dates, recovery URL, token, discount codes,
landing/referring site, total weight and shipping/billing address fields.

The following custom fields are fallbacks or EasyStore-specific facts. As with
Orders, a fallback is created only if the live portal has no unambiguous writable
native equivalent of the same type.

| Custom property | Cart fact |
| --- | --- |
| `easystore_cart_status` | EasyStore checkout status |
| `easystore_cart_total_amount` | total |
| `easystore_cart_subtotal_amount` | subtotal |
| `easystore_cart_discount_amount` | discount amount |
| `easystore_cart_tax_amount` | tax |
| `easystore_cart_shipping_amount` | shipping |
| `easystore_cart_tags` | tags |
| `easystore_cart_created_at` | checkout creation time |
| `easystore_cart_abandoned_at` | last activity/abandonment time |
| `easystore_cart_recovery_url` | recovery/resume URL |
| `easystore_cart_item_count` | item/unit count |
| `easystore_cart_items` | human-readable cart contents |
| `easystore_cart_email` | buyer email |
| `easystore_cart_customer_name` | buyer name |
| `easystore_cart_phone` | buyer mobile |
| `easystore_cart_is_abandoned` | integration's normalized abandoned flag |

Native-only Cart fields that do not get custom duplicates include
`hs_external_token`, `hs_discount_codes`, `hs_landing_site`, `hs_referring_site`,
`hs_total_weight`, and the native shipping/billing address fields.

## Cloudflare source-attribution Contact fields

These are intentionally custom rather than mapped into HubSpot's own analytics
properties. HubSpot owns and enumerates its analytics-source fields; writing the
Cloudflare attribution vocabulary into those fields would change semantics or
reject values.

All live in the `cloudflare_attribution` property group:

| Custom Contact property | Meaning |
| --- | --- |
| `cc_acquisition_click_id` | immutable acquisition click ID |
| `cc_acquisition_source` | acquisition source |
| `cc_acquisition_medium` | acquisition medium |
| `cc_acquisition_campaign` | campaign |
| `cc_acquisition_entry_path` | tracked `/go/*` entry path |
| `cc_acquisition_country` | Cloudflare country |
| `cc_acquisition_at` | click timestamp |
| `cc_acquisition_automated` | link-preview/prefetch automation reason |

The click ID that connects EasyStore to this stage normally arrives through a
merchant-defined Contact attribute such as `easystore_attr_click_id`, covered by
the dynamic Contact attribute rule above.

## What can be relied on in HubSpot automation/reporting

A field listed as **native/direct** above is populated when the source value is
present. A field listed as **native-first with fallback** must be read from the
actual mapping reported by the sync run (`hubspot_*_field_properties` in the JSON
summary), because different HubSpot portals can expose different writable native
schemas. The run summary is authoritative for which property received each fact
on that portal.

Do not build a new workflow against an `easystore_*` fallback merely because it
exists in the property picker. Check the current sync summary first: if the field
now resolves to a native HubSpot property, the legacy custom field is retained
only to protect historical data and is no longer the live destination.

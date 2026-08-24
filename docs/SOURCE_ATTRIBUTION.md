# Source attribution

This integration uses one Cloudflare click history for two separate questions:

- **Contact acquisition**: which tracked marketing touch most recently preceded account creation?
- **Order source**: which tracked marketing touch most recently preceded this specific purchase?

Neither model uses an EasyStore `Click ID` customer attribute, and HubSpot does
not store click UUIDs. Click UUIDs are internal transport/join keys inside
Cloudflare D1 only.

## Data model

```text
tracked marketing URL
        ↓
go.cardboard.sg / cc-attribution
        ↓
source_clicks
(click UUID + source + medium + campaign + content + clicked_at)
        ↓
EasyStore storefront
(latest click held briefly in browser cookie/localStorage)
        ↓
logged-in customer.id + click UUID
        ↓
customer_touches
(append-only EasyStore customer ID ↔ click relation)
        ↓
        ├── Contact acquisition
        │   EasyStore customer ID + customer created_at
        │   → latest human touch before signup
        │
        └── Order attribution
            EasyStore customer ID + order created_at
            → latest human touch before order
```

The browser never tells Cloudflare what source/campaign a click represents. It
only returns a Worker-minted UUID. The Worker accepts a touch only when that UUID
already exists in `source_clicks` and is human traffic.

## No EasyStore Click ID attribute

The previous design copied a click UUID through:

```text
browser → EasyStore customer "Click ID" attribute
        → HubSpot easystore_attr_click_id
        → D1 lookup
```

That bridge is retired.

The production Customer sync now filters these legacy merchant-attribute titles
out instead of provisioning/writing them to HubSpot:

- `Click ID`
- `ClickID`
- `cb_click_id`
- `Source click ID`
- `Attribution click ID`

The theme's `attribution-click-id-field` snippet is now only a temporary rollout
guard: if the old EasyStore attribute still exists, it hides/disables it and
removes its form `name` so shoppers cannot submit it. It never fills a value.
Once the old attribute is deleted in EasyStore admin, that snippet becomes a
no-op.

Existing historical HubSpot properties such as `easystore_attr_click_id`,
`cc_acquisition_click_id` or `cc_order_click_id` may remain in the portal, but
this integration no longer reads or writes them. They can be archived/deleted
separately after rollout if desired.

## Contact acquisition model

`scripts/cloudflare_hubspot_attribution.py` runs after the Customer sync.

The Customer sync supplies two ordinary EasyStore facts on the HubSpot Contact:

```text
easystore_customer_id
easystore_customer_created_at
```

For each Contact without an existing acquisition snapshot, attribution selects:

```text
latest human customer_touches/source_clicks row
where customer_id = easystore_customer_id
and clicked_at <= easystore_customer_created_at
and clicked_at >= easystore_customer_created_at - 30 days
```

`bound_at` is **not** required to precede account creation for acquisition. A
shopper can register, land on the first authenticated page, and only then bind
the already-existing pre-signup click to the new customer ID. The click timestamp
itself must still be before signup.

Default model:

```text
last_tracked_touch_before_signup
window = 30 days
```

Override only if needed:

```text
ACQUISITION_ATTRIBUTION_WINDOW_DAYS=30
```

### HubSpot Contact properties

The integration writes marketing facts, not a click UUID:

| HubSpot Contact property | Meaning |
| --- | --- |
| `cc_acquisition_source` | selected source (`facebook`, `whatsapp`, etc.) |
| `cc_acquisition_medium` | selected medium |
| `cc_acquisition_campaign` | campaign label |
| `cc_acquisition_content` | post/ad/message label |
| `cc_acquisition_entry_path` | tracking path used |
| `cc_acquisition_country` | country Cloudflare reported |
| `cc_acquisition_at` | selected touch timestamp |
| `cc_acquisition_attribution_model` | `last_tracked_touch_before_signup` |
| `cc_acquisition_attribution_window_days` | `30` by default |
| `cc_acquisition_status` | `attributed` or `no_recent_tracked_touch` |

An existing acquisition snapshot is immutable. A `no_recent_tracked_touch`
status is intentionally retryable: if the browser binds its pre-signup touch on a
later authenticated page, a future CRM run may upgrade the Contact to
`attributed`.

If the same `easystore_customer_id` appears on multiple HubSpot Contacts, the
stage refuses to guess and attributes none of those duplicates.

## Order attribution

Order attribution uses the same `customer_touches` history but a different time
cutoff. See `docs/ORDER_SOURCE_ATTRIBUTION.md` for the operating guide.

The key difference is:

- acquisition permits the binding itself to happen just after signup, because the
  pre-signup click timestamp proves when the marketing touch happened;
- an Order requires `bound_at <= order.created_at`, so a touch learned after the
  purchase cannot retroactively claim revenue.

## Marketing URLs

Campaigns and posts do not need to be predefined in code.

Use:

```text
https://go.cardboard.sg/<platform>?campaign=<campaign>&content=<content>&to=<store-path>
```

Example:

```text
https://go.cardboard.sg/fb?campaign=rf&content=grp-aug26&to=/collections/reality-fracture
```

The Worker redirects to the store with normal UTMs plus its internal click UUID:

```text
utm_source=facebook
utm_medium=social
utm_campaign=rf
utm_content=grp-aug26
cb_click_id=<worker UUID>
```

The UUID is consumed by the storefront/Worker touch binding; it is not a CRM
field.

### Platform codes

| Code | Source | Medium |
| --- | --- | --- |
| `fb` | `facebook` | `social` |
| `ig` | `instagram` | `social` |
| `tt` | `tiktok` | `social` |
| `wa` | `whatsapp` | `messaging` |
| `ca` | `carousell` | `marketplace` |
| `em` | `email` | `email` |
| `qr` | `qr` | `offline` |

A new campaign/content label needs no deploy. A completely new platform/source
code needs a `CHANNELS` entry in `cloudflare/attribution-worker/src/index.js` so
reporting names stay canonical.

`to` is optional and must be a relative storefront path beginning with `/`.
Absolute/external destinations are discarded so the tracking hostname cannot
become an open redirect.

## Recommended naming

Use short, stable, lowercase labels:

```text
campaign=rf
content=grp-aug26
content=grp-bump-aug26
```

Use `campaign` for the initiative/product/launch and `content` for the exact
creative, post or message.

## Deployment order

1. Merge only after Worker/CRM/theme tests are green.
2. Apply D1 migration `0003_order_source_attribution.sql` before Worker deploy.
   The Worker deployment workflow enforces this ordering and runs the migration
   command twice to prove the Wrangler migration ledger makes reruns a no-op.
3. Hand `go.cardboard.sg` from the temporary `cc-rf` Worker to `cc-attribution`.
4. Deploy the updated theme so logged-in customers bind source clicks directly to
   `customer.id`.
5. Delete the old EasyStore `Click ID` customer attribute. The rollout guard means
   this can happen immediately before or after the theme deploy without exposing
   or submitting the field.
6. Run Customer sync / source attribution and then the two-platform Order smoke
   test from `docs/ORDER_SOURCE_ATTRIBUTION.md`.

## Verification

Use a test link while signed in:

```text
https://go.cardboard.sg/wa?campaign=tracking-test&content=source-smoke&to=/
```

Confirm:

1. the redirect contains WhatsApp UTMs and `cb_click_id`;
2. a D1 `source_clicks` row exists;
3. a D1 `customer_touches` row exists for the EasyStore customer ID;
4. Customer sync has written `easystore_customer_id` and
   `easystore_customer_created_at` to the Contact;
5. source attribution writes `cc_acquisition_*` without writing any Click ID
   property.

Useful D1 checks:

```sql
SELECT source, campaign, content, clicked_at
FROM source_clicks
WHERE bot = 0
ORDER BY clicked_at DESC
LIMIT 20;
```

```sql
SELECT customer_id, bound_at
FROM customer_touches
ORDER BY bound_at DESC
LIMIT 20;
```

## Limits

- Only tracked URLs create deterministic source rows. Organic/direct/untracked
  links cannot be assigned a deterministic marketing source by this model.
- A cleared browser can lose an unbound click.
- Cross-device journeys are not deterministic unless the relevant click becomes
  bound to the purchasing customer's ID on that device.
- Browsers blocking JavaScript/storage can prevent binding.
- Touch history begins when `customer_touches` is deployed; old journeys that
  were never recorded cannot be reconstructed reliably.
- `no_recent_tracked_touch` means exactly that. Do not relabel it `direct` without
  separate evidence.

## Files

| Part | File |
| --- | --- |
| Worker click creation/touch endpoint | `cloudflare/attribution-worker/src/index.js` |
| D1 schema | `cloudflare/attribution-worker/migrations/` |
| Storefront touch binding | `theme/snippets/attribution-click-id.liquid` |
| Legacy EasyStore field suppression | `theme/snippets/attribution-click-id-field.liquid` |
| Customer sync / legacy field filter | `scripts/easystore_hubspot_customer_sync.py` |
| Contact acquisition | `scripts/cloudflare_hubspot_attribution.py` |
| Order attribution | `scripts/cloudflare_hubspot_order_attribution.py` |
| Contact attribution tests | `crm_tests/test_cloudflare_attribution.py` |
| Order attribution tests | `crm_tests/test_order_source_attribution.py` |

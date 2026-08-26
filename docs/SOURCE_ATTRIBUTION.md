# Source attribution

This integration uses one Cloudflare click history for two separate attribution
questions and one advertising-identity job:

- **Contact acquisition**: which tracked marketing touch most recently preceded account creation?
- **Order source**: which tracked marketing touch most recently preceded this specific purchase?
- **Native ad click IDs**: what is the latest bound Google/Meta/TikTok/LinkedIn
  vendor identifier that HubSpot can use when syncing conversion events?

The internal Worker click UUID and advertising-network click IDs are deliberately
different things. Worker UUIDs remain transport/join keys inside Cloudflare D1
only. HubSpot never receives a Worker UUID.

## Data model

```text
tracked marketing URL
        ↓
go.cardboard.sg / cc-attribution
        ↓
source_clicks
(Worker UUID + source + medium + campaign + content + clicked_at)
        ↓
source_click_identifiers
(Worker UUID + gclid/fbclid/ttclid/li_fat_id/gbraid/wbraid)
        ↓
EasyStore storefront
(latest Worker UUID held briefly in browser cookie/localStorage;
 vendor click parameters forwarded to the landing page)
        ↓
logged-in customer.id + Worker UUID
        ↓
customer_touches
(append-only EasyStore customer ID ↔ Worker click relation)
        ↓
        ├── Contact acquisition
        │   EasyStore customer ID + customer created_at
        │   → latest human touch before signup
        │
        ├── Native ad click IDs
        │   EasyStore customer ID
        │   → latest bound supported vendor ID per network
        │   → HubSpot native hs_*_click_id fields
        │
        └── Order attribution
            EasyStore customer ID + order created_at
            → latest human touch before order
```

The browser never tells Cloudflare what source/campaign an existing Worker click
represents. It only returns a Worker-minted UUID. The Worker accepts a customer
touch only when that UUID already exists in `source_clicks` and is human traffic.

Vendor click IDs are captured only on the initial tracked GET request and stored
alongside that trusted Worker click. They are not used as the Cloudflare
customer-binding key.

## No EasyStore Click ID attribute

The previous design copied a Worker click UUID through:

```text
browser → EasyStore customer "Click ID" attribute
        → HubSpot easystore_attr_click_id
        → D1 lookup
```

That bridge is retired.

The production Customer sync filters these legacy merchant-attribute titles out
instead of provisioning/writing them to HubSpot:

- `Click ID`
- `ClickID`
- `cb_click_id`
- `Source click ID`
- `Attribution click ID`

The theme's `attribution-click-id-field` snippet is only a rollout guard: if the
old EasyStore attribute still exists, it hides/disables it and removes its form
`name` so shoppers cannot submit it. It never fills a value.

Existing historical HubSpot properties such as `easystore_attr_click_id`,
`cc_acquisition_click_id` or `cc_order_click_id` may remain in the portal, but
this integration no longer reads or writes them.

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

### HubSpot Contact acquisition properties

| HubSpot Contact property | Meaning |
| --- | --- |
| `cc_acquisition_source` | selected source (`facebook`, `google`, etc.) |
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
status is retryable: if the browser binds its pre-signup touch on a later
authenticated page, a future CRM run may upgrade the Contact to `attributed`.

If the same `easystore_customer_id` appears on multiple HubSpot Contacts, the
stage refuses to guess and updates none of those duplicates.

## Native advertising click IDs

The Worker allowlists these incoming URL parameters:

| Parameter | Network | HubSpot Contact property |
| --- | --- | --- |
| `gclid` | Google Ads | `hs_google_click_id` |
| `fbclid` | Meta/Facebook | `hs_facebook_click_id` |
| `ttclid` | TikTok | `hs_tiktok_click_id` |
| `li_fat_id` | LinkedIn | `hs_linkedin_click_id` |
| `gbraid` | Google Ads | D1 + landing-page passthrough only |
| `wbraid` | Google Ads | D1 + landing-page passthrough only |

Identifiers are preserved case-sensitively and are not normalized like campaign
labels.

`gbraid` and `wbraid` are deliberately **not** written into
`hs_google_click_id`; HubSpot's native property represents GCLID. They remain
available in D1 and on the redirected landing URL for future platform-specific
handling.

### Rolling selection rule

Native ad identity is independent of the immutable acquisition snapshot.

For every uniquely mapped EasyStore customer, the CRM job selects the newest
bound human click for each supported vendor parameter. A later Google click can
therefore update `hs_google_click_id` without rewriting the Contact's original
Facebook acquisition.

The integration also owns these companion timestamps:

```text
cc_google_click_at
cc_facebook_click_at
cc_tiktok_click_at
cc_linkedin_click_at
```

They make writes monotonic. An older D1 click cannot overwrite a newer value
already written by this integration.

If a HubSpot native click-ID field already contains a *different* value and no
companion `cc_*_click_at` timestamp exists, the integration preserves the
HubSpot value rather than guessing which source is newer.

The click-ID `FieldSpec`s have no custom fallback. If HubSpot does not expose a
native property as writable, the job reports it in
`unwritable_or_missing_native_ad_click_properties` instead of pretending a
custom field is conversion-compatible.

## Order attribution

Order attribution uses the same `customer_touches` history but a different time
cutoff. See `docs/ORDER_SOURCE_ATTRIBUTION.md` for the operating guide.

The key difference is:

- acquisition permits the binding itself to happen just after signup, because the
  pre-signup click timestamp proves when the marketing touch happened;
- an Order requires `bound_at <= order.created_at`, so a touch learned after the
  purchase cannot retroactively claim revenue.

Vendor click-ID enrichment is Contact-level and rolling; it does not replace the
per-Order `cc_order_*` attribution snapshot.

## Marketing URLs

Campaigns and posts do not need to be predefined in code.

Use:

```text
https://go.cardboard.sg/<platform>?campaign=<campaign>&content=<content>&to=<store-path>
```

Example:

```text
https://go.cardboard.sg/gg?campaign=rf&content=google-search-01&to=/collections/reality-fracture
```

The Worker redirects to the store with normal UTMs plus its internal Worker UUID
and any supported vendor click parameter that arrived on the request:

```text
utm_source=google
utm_medium=cpc
utm_campaign=rf
utm_content=google-search-01
cb_click_id=<worker UUID>
gclid=<Google-provided identifier, when present>
```

The Worker UUID is consumed by the storefront/Worker touch binding. It is never a
CRM advertising click-ID value.

### Platform codes

| Code | Source | Medium |
| --- | --- | --- |
| `gg` | `google` | `cpc` |
| `fb` | `facebook` | `social` |
| `ig` | `instagram` | `social` |
| `tt` | `tiktok` | `social` |
| `li` | `linkedin` | `social` |
| `wa` | `whatsapp` | `messaging` |
| `ca` | `carousell` | `marketplace` |
| `em` | `email` | `email` |
| `qr` | `qr` | `offline` |

A new campaign/content label needs no deploy. A completely new platform/source
code needs a `CHANNELS` entry in
`cloudflare/attribution-worker/src/index.js` so reporting names stay canonical.

`to` is optional and must be a relative storefront path beginning with `/`.
Absolute/external destinations are discarded so the tracking hostname cannot
become an open redirect.

See `docs/MARKETING_LINKS.md` for the distinction between the public
`cardboard.sg` business URL and the `go.cardboard.sg` paid-ad click router.

## Deployment order

1. Merge only after Worker/CRM/theme tests are green.
2. The Worker deployment workflow applies pending remote D1 migrations before
   Worker deploy. Migration `0005_native_ad_click_ids.sql` must therefore land
   before the new Worker code runs in production.
3. Deploy the updated Worker on `go.cardboard.sg`.
4. Keep the theme's storefront touch binding deployed.
5. Run Customer sync / Cloudflare Contact sync and then an ad-click smoke test.

## Verification

Use a signed-in test link:

```text
https://go.cardboard.sg/gg?campaign=tracking-test&content=native-id-smoke&gclid=TEST-GCLID&to=/
```

Confirm:

1. the redirect contains Google UTMs, `cb_click_id`, and `gclid=TEST-GCLID`;
2. a D1 `source_clicks` row exists;
3. a D1 `source_click_identifiers` row exists for `gclid`;
4. a D1 `customer_touches` row exists for the EasyStore customer ID;
5. Customer sync has written `easystore_customer_id`;
6. source attribution writes the acquisition snapshot without a Worker UUID;
7. if `hs_google_click_id` is writable, it receives `TEST-GCLID` and
   `cc_google_click_at` receives the Cloudflare click time.

Useful D1 checks:

```sql
SELECT source, campaign, content, clicked_at
FROM source_clicks
WHERE bot = 0
ORDER BY clicked_at DESC
LIMIT 20;
```

```sql
SELECT
  sc.clicked_at,
  sci.network,
  sci.parameter,
  sci.identifier
FROM source_click_identifiers AS sci
JOIN source_clicks AS sc ON sc.click_id = sci.click_id
ORDER BY sc.clicked_at DESC
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
- Vendor click IDs are captured only when the paid click reaches the Worker
  route. A platform link that sends the shopper directly to `cardboard.sg`
  bypasses this D1 capture path.
- A cleared browser can lose an unbound click.
- Cross-device journeys are not deterministic unless the relevant click becomes
  bound to the purchasing customer's ID on that device.
- Browsers blocking JavaScript/storage can prevent binding.
- Touch history begins when `customer_touches` is deployed; old journeys that
  were never recorded cannot be reconstructed reliably.
- `no_recent_tracked_touch` means exactly that. Do not relabel it `direct`
  without separate evidence.

## Files

| Part | File |
| --- | --- |
| Worker click creation/touch endpoint | `cloudflare/attribution-worker/src/index.js` |
| D1 schema | `cloudflare/attribution-worker/migrations/` |
| Storefront touch binding | `theme/snippets/attribution-click-id.liquid` |
| Customer sync / legacy field filter | `scripts/easystore_hubspot_customer_sync.py` |
| Contact acquisition + native ad IDs | `scripts/cloudflare_hubspot_attribution.py` |
| Order attribution | `scripts/cloudflare_hubspot_order_attribution.py` |
| Contact attribution tests | `crm_tests/test_cloudflare_attribution.py` |
| Order attribution tests | `crm_tests/test_order_source_attribution.py` |

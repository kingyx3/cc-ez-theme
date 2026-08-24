# Order source attribution

This document is the operating guide for deterministic **per-order marketing
source** tracking.

It is intentionally separate from customer acquisition attribution:

- **Contact acquisition** answers: _which tracked click acquired this account?_
- **Order source** answers: _which tracked marketing touch most recently led this
  customer back to the store before this specific purchase?_

A repeat customer's later order is therefore not forced to inherit the platform
that originally caused sign-up.

## Attribution model

The order model is **last tracked human touch before the order**, with a 30-day
window by default.

For an EasyStore order to receive a source, the selected click must:

1. exist in Cloudflare D1 `source_clicks`;
2. be a human click (`bot = 0`);
3. have been bound to the order's EasyStore `customer_id` before the order was
   created;
4. have happened before the order was created; and
5. be no older than `ORDER_ATTRIBUTION_WINDOW_DAYS`.

There is **no fallback to the Contact's acquisition source**. If no qualifying
tracked touch exists, the Order gets `cc_order_attribution_status =
no_recent_tracked_touch` and no marketing source is invented.

Example:

| Time | Event | Result |
| --- | --- | --- |
| 1 Aug | Facebook link, customer signs up | Contact acquisition = Facebook |
| 10 Aug | Purchase | Order A = Facebook if that touch is still eligible |
| 20 Aug | WhatsApp tracked link | new customer touch = WhatsApp |
| 21 Aug | Purchase | Order B = WhatsApp |
| 23 Aug | Facebook RF bump link | new customer touch = Facebook / RF bump |
| 24 Aug | Purchase | Order C = Facebook / RF bump |

The three Orders remain independent snapshots even though they belong to the same
customer.

## Data flow

```text
marketing link
    ↓
go.cardboard.sg Worker
    ↓
source_clicks (D1)
    ↓ cb_click_id + normal UTMs
EasyStore storefront
    ↓
logged-in customer + latest click id
    ↓
customer_touches (D1, append-only)
    ↓
EasyStore Order customer_id + created_at
    ↓
cloudflare_hubspot_order_attribution.py
    ↓
HubSpot Order cc_order_*
```

The existing EasyStore customer `Click ID` attribute remains write-once and is
still used for Contact acquisition. The browser's current `cb_click_id`, however,
is refreshed by every tracked marketing entry so it can represent later touches.

## Marketing URLs: campaigns do not need to be predefined

Ordinary campaigns should use the generic URL format:

```text
https://go.cardboard.sg/<platform>?campaign=<campaign>&content=<content>&to=<store-path>
```

Example:

```text
https://go.cardboard.sg/fb?campaign=rf&content=grp-aug26&to=/collections/reality-fracture
```

The Worker generates the destination UTMs automatically:

```text
utm_source=facebook
utm_medium=social
utm_campaign=rf
utm_content=grp-aug26
cb_click_id=<new UUID>
```

### Supported platform codes

| Code | `utm_source` / order source | `utm_medium` |
| --- | --- | --- |
| `fb` | `facebook` | `social` |
| `ig` | `instagram` | `social` |
| `tt` | `tiktok` | `social` |
| `wa` | `whatsapp` | `messaging` |
| `ca` | `carousell` | `marketplace` |
| `em` | `email` | `email` |
| `qr` | `qr` | `offline` |

**Campaign names and content/post names do not require a code change or Worker
redeploy.** Put them in the query string.

A new **platform/source** does require adding one entry to `CHANNELS` in
`cloudflare/attribution-worker/src/index.js`. This is deliberate: source and
medium names stay canonical instead of accumulating spelling variants in reports.

### Campaign naming

Use short, stable, lowercase labels. The Worker normalizes labels automatically,
but the marketing team should still pick one canonical name.

Recommended:

```text
campaign=rf
content=grp-aug26
content=grp-bump-aug26
```

Avoid embedding dates into `campaign` if several posts are part of one campaign.
Put the individual post/ad/message identifier in `content` instead.

A useful naming split is:

- `campaign`: initiative/product/launch (`rf`, `ff`, `restock`)
- `content`: exact creative/post/message (`grp-aug26`, `retarget-01`, `vip-blast`)

### Destination paths

`to` is optional. When omitted, the tracked link lands on the storefront home
page.

```text
https://go.cardboard.sg/fb?campaign=rf&content=grp-aug26
```

To deep-link:

```text
&to=/collections/reality-fracture
```

Only a relative path beginning with `/` is accepted. Absolute/external URLs and
`//host` forms are discarded, preventing the tracking domain from becoming an
open redirect.

## Vanity links

Vanity URLs are optional. Use them when a link needs to be short, memorable or
already published externally.

The Worker preserves the live Reality Fracture links:

```text
https://go.cardboard.sg/rf
https://go.cardboard.sg/rf-bump
```

They resolve to:

| Alias | Source | Campaign | Content | Destination |
| --- | --- | --- | --- | --- |
| `/rf` | Facebook | `rf` | `grp-aug26` | `/collections/reality-fracture` |
| `/rf-bump` | Facebook | `rf` | `grp-bump-aug26` | `/collections/reality-fracture` |

Unlike ordinary campaign URLs, a new vanity alias is predefined in the Worker's
`ALIASES` map and therefore requires a PR/deploy. Do not create aliases for every
post; generic campaign URLs are intended to avoid that maintenance burden.

## HubSpot Order properties

The attribution job provisions these properties on HubSpot Orders:

| Property | Meaning |
| --- | --- |
| `cc_order_source` | source of the selected touch (`facebook`, `whatsapp`, etc.) |
| `cc_order_medium` | medium of the selected touch |
| `cc_order_campaign` | campaign label |
| `cc_order_content` | exact post/ad/message label |
| `cc_order_click_id` | immutable selected Cloudflare click UUID |
| `cc_order_touch_at` | selected click timestamp |
| `cc_order_attribution_model` | `last_tracked_touch` |
| `cc_order_attribution_window_days` | configured lookback window |
| `cc_order_attribution_status` | `attributed`, `no_recent_tracked_touch`, or a missing-source-data reason |

`hs_source_store` remains the commerce storefront (`cardboard.sg`) and
`easystore_order_channel` remains whatever sales channel EasyStore itself
reports. Neither field is repurposed as marketing attribution.

If an Order already has a different `cc_order_click_id`, the job reports a
conflict and refuses to overwrite the historical snapshot.

## Storefront touch binding

`theme/snippets/attribution-click-id.liquid` runs globally before navigation can
lose the incoming click ID.

When EasyStore exposes a logged-in `customer.id`, the script sends only:

```json
{
  "customer_id": "12345",
  "click_id": "<UUID>"
}
```

to `https://go.cardboard.sg/touch`.

No name, email, phone or profile fields are sent. The Worker also refuses a touch
unless the click ID already exists in `source_clicks` and is human traffic.
`customer_touches` is append-only, so retrying the request cannot move the first
binding timestamp forward.

If a shopper lands while logged out, the click stays in first-party browser
storage. After the shopper signs in or registers, the next storefront page binds
that stored click to the customer before a later purchase can use it.

## Deployment requirements

### 1. Apply the D1 migration

From `cloudflare/attribution-worker`:

```bash
npm install
npm run d1:migrate:remote
```

Migration `0003_order_source_attribution.sql` adds `source_clicks.content` and the
append-only `customer_touches` table.

Apply the migration **before** deploying the Worker code that writes `content`.

### 2. Move `go.cardboard.sg` to `cc-attribution`

`wrangler.jsonc` now makes `go.cardboard.sg` a Cloudflare Worker Custom Domain.
This is intentional: the EasyStore apex/www DNS can remain DNS-only while the
tracking hostname is proxied/served directly by Cloudflare.

The temporary `cc-rf` Worker currently owning `go.cardboard.sg` must be removed
from that custom domain before deploying `cc-attribution`; two Workers cannot own
the same Custom Domain.

Then deploy:

```bash
npm run deploy
```

Smoke test both old and generic links before deleting the temporary Worker:

```text
https://go.cardboard.sg/rf
https://go.cardboard.sg/rf-bump
https://go.cardboard.sg/fb?campaign=tracking-test&content=smoke&to=/
```

### 3. Deploy the EasyStore theme

The updated global attribution snippet must be live so logged-in customers bind
tracked touches. HubSpot's tracking script may continue to be injected by the
EasyStore Code Insert app; this order-source implementation does not require a
second HubSpot browser loader in the theme.

### 4. GitHub Environment credentials

The `prod` and `dev` GitHub environments used by the attribution workflow need:

Secrets:

```text
EASYSTORE_ACCESS_TOKEN
HUBSPOT_ACCESS_TOKEN
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
```

Variable:

```text
EASYSTORE_STORE_DOMAIN
```

Optional variable:

```text
ORDER_ATTRIBUTION_WINDOW_DAYS=30
```

The Cloudflare token needs D1 read access. The HubSpot token needs Order read/write
and CRM schema read/write access because the job provisions the `cc_order_*`
properties on first use.

The workflow runs one hour after the existing six-hour CRM sync so HubSpot Orders
are present before attribution. It can also be dispatched manually for `dev` or
`prod` with a chosen window.

## Production smoke test

Use a fresh test sequence after deployment:

1. Open a generic tracked URL such as:

   ```text
   https://go.cardboard.sg/wa?campaign=tracking-test&content=message-a&to=/
   ```

2. Confirm the redirect contains:
   - `utm_source=whatsapp`
   - `utm_medium=messaging`
   - `utm_campaign=tracking-test`
   - `utm_content=message-a`
   - a UUID `cb_click_id`
3. While signed in, browse another storefront page so the `/touch` request can
   retry if necessary.
4. Place an order.
5. Run **Sync order source attribution** for `prod` manually.
6. Confirm the HubSpot Order contains `cc_order_source=whatsapp`, the test
   campaign/content, and the same click UUID.
7. Open a Facebook tracked URL with a different `content`, place a second order,
   rerun the workflow, and verify only the second Order receives the Facebook
   touch. The first Order must stay WhatsApp.

## Reporting examples

Once Orders carry the snapshot properties, reports can group/sum Order revenue
by:

- `cc_order_source`
- `cc_order_campaign`
- `cc_order_content`
- source + campaign
- campaign + content

Contact acquisition reports should continue using `cc_acquisition_*`. Do not mix
the two property families without explicitly naming which attribution question a
report answers.

## Known limits

- Touch history starts when this rollout goes live. Historical Orders cannot be
  deterministically reconstructed from browser state that was never recorded.
- An untracked external link has no D1 click and therefore cannot receive a
  deterministic order source even if HubSpot browser analytics recognizes a
  session source.
- Cross-device journeys are not deterministic: a marketing click on device A
  cannot automatically become the Order touch for a purchase made on device B.
- A browser blocking JavaScript/storage can prevent the customer-touch binding.
- `no_recent_tracked_touch` means exactly that; it must not be relabelled
  "direct" unless there is separate evidence the session was direct.

# Order source attribution

This is the operating guide for deterministic **per-order marketing source** tracking.

It is intentionally separate from customer acquisition attribution:

- **Contact acquisition** answers: which tracked marketing touch most recently preceded account creation?
- **Order source** answers: which tracked marketing touch most recently preceded this specific purchase?

A repeat customer can therefore have different sources on different Orders without
changing the Contact's original acquisition source.

## Attribution model

The Order model is **last tracked human touch before the Order**, with a default
lookback window of **30 days**.

A touch can attribute an EasyStore Order only when it:

1. exists in Cloudflare D1 `source_clicks`;
2. is human traffic (`bot = 0`);
3. was bound to the same EasyStore `customer_id` in `customer_touches`;
4. has `clicked_at <= order.created_at`;
5. has `bound_at <= order.created_at`; and
6. is no older than 30 days before the Order.

There is **no fallback to Contact acquisition**. If no qualifying tracked touch
exists, the Order gets `cc_order_attribution_status = no_recent_tracked_touch` and
no marketing source is invented.

Example:

| Time | Event | Result |
| --- | --- | --- |
| 1 Aug | Facebook tracked link, customer signs up | Contact acquisition = Facebook |
| 10 Aug | Purchase | Order A = Facebook if the touch is still eligible |
| 20 Aug | WhatsApp tracked link | latest customer touch = WhatsApp |
| 21 Aug | Purchase | Order B = WhatsApp |
| 23 Aug | Instagram tracked link | latest customer touch = Instagram |
| 24 Aug | Purchase | Order C = Instagram |

Each Order is its own immutable attribution snapshot.

## Clean click-history model

Click UUIDs exist only as internal Cloudflare join keys:

```text
marketing URL
    ↓
go.cardboard.sg Worker
    ↓
source_clicks
    ↓
customer_touches
    ↓
EasyStore Order customer_id + created_at
    ↓
cloudflare_hubspot_order_attribution.py
    ↓
HubSpot Order cc_order_*
```

The storefront sends `customer_id + click_id` to Cloudflare's `/touch` endpoint,
but HubSpot does **not** store the click UUID. The UUID is only how D1 relates the
browser touch to its source row.

The old EasyStore `Click ID` customer attribute is not used. Customer sync filters
it out, and the theme only suppresses the legacy field while it is being removed
from EasyStore admin.

## Marketing URLs

Campaigns/posts **do not need to be predefined**.

Use:

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
cb_click_id=<internal Worker UUID>
```

The browser/Worker use `cb_click_id` to build D1 touch history. It is not an
EasyStore customer field and is not a HubSpot property.

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

A new campaign/content value does not need a code change or Worker deploy. A new
**platform/source** does require a `CHANNELS` entry so reports do not accumulate
spelling variants.

### Campaign naming

Use short, stable, lowercase labels.

Recommended:

```text
campaign=rf
content=grp-aug26
content=grp-bump-aug26
```

Use:

- `campaign` for the initiative/product/launch (`rf`, `restock`, `one-piece`)
- `content` for the exact creative/post/message (`grp-aug26`, `retarget-01`, `vip-blast`)

### Destination paths

`to` is optional. Omit it to land on the storefront home page.

```text
https://go.cardboard.sg/fb?campaign=rf&content=grp-aug26
```

For a deep link:

```text
https://go.cardboard.sg/fb?campaign=rf&content=grp-aug26&to=/collections/reality-fracture
```

Only a relative path beginning with `/` is accepted. Absolute URLs and `//host`
forms are rejected, so `go.cardboard.sg` cannot be used as an open redirect.

There are no `/rf` or `/rf-bump` special aliases. Use generic campaign URLs.

## HubSpot Order properties

The attribution job provisions/writes:

| Property | Meaning |
| --- | --- |
| `cc_order_source` | source of selected touch (`facebook`, `whatsapp`, etc.) |
| `cc_order_medium` | medium of selected touch |
| `cc_order_campaign` | campaign label |
| `cc_order_content` | exact post/ad/message label |
| `cc_order_touch_at` | selected marketing touch timestamp |
| `cc_order_attribution_model` | `last_tracked_touch` |
| `cc_order_attribution_window_days` | `30` by default |
| `cc_order_attribution_status` | `attributed`, `no_recent_tracked_touch`, or missing-source-data reason |

There is no `cc_order_click_id` dependency. If an old `cc_order_click_id` property
exists in the HubSpot portal from earlier development, this integration ignores
and never writes it.

`hs_source_store` remains the commerce storefront (`cardboard.sg`) and
`easystore_order_channel` remains whatever sales channel EasyStore itself reports.
Neither field is repurposed as marketing attribution.

Once an Order has a real attribution snapshot (`cc_order_attribution_status =
attributed`, or populated source/touch fields), later runs leave it unchanged.
A `no_recent_tracked_touch` status is not locked and can upgrade if a valid touch
that was already bound before the Order later becomes visible to the sync.

## Storefront touch binding

`theme/snippets/attribution-click-id.liquid` runs globally early in the page.

When EasyStore exposes a logged-in `customer.id`, the script sends only:

```json
{
  "customer_id": "12345",
  "click_id": "<internal Worker UUID>"
}
```

to `https://go.cardboard.sg/touch`.

No name, email, phone or profile fields are sent. The Worker refuses the binding
unless the UUID already exists in `source_clicks` and is human traffic.
`customer_touches` is append-only/idempotent.

If a shopper lands while logged out, the click remains in browser storage. Once
they are authenticated, a storefront page binds that latest click to their
EasyStore customer ID.

## Deployment requirements

### 1. Apply D1 migrations before Worker deployment

The repository Worker deployment workflow enforces:

```text
validate/tests
→ apply pending D1 migrations
→ run the migration command again (must be a no-op)
→ deploy Worker
```

Migration `0003_order_source_attribution.sql` adds:

- `source_clicks.content`
- append-only `customer_touches`

PR validation also applies the complete local migration set twice. Wrangler's
D1 migration ledger records applied migration files, making reruns idempotent.

### 2. Hand `go.cardboard.sg` to `cc-attribution`

The final Worker owns `go.cardboard.sg` as a Cloudflare Worker Custom Domain.
The EasyStore apex/www DNS stays unchanged.

Cutover:

1. Cloudflare → Workers & Pages → temporary `cc-rf` Worker → Settings → Domains & Routes.
2. Remove/detach `go.cardboard.sg` from `cc-rf`.
3. Run/deploy the repository `cc-attribution` Worker.
4. Verify `https://go.cardboard.sg/health` identifies `cc-attribution`.
5. Test a generic tracking URL.
6. Delete `cc-rf` only after the handoff works and only if it has no other routes/purpose.

You do **not** need to delete `cc-rf` before detaching the domain.

### 3. Deploy the EasyStore theme

The updated global capture snippet must be live so authenticated shoppers bind
tracked touches directly to their EasyStore customer ID.

The existing HubSpot tracking script can continue to be injected by the EasyStore
Code Insert app. This attribution system does not add a second HubSpot loader.

### 4. Remove the old EasyStore Click ID attribute

Delete the old machine-only `Click ID` customer attribute from EasyStore admin.

The theme contains a temporary compatibility suppressor that hides/disables the
old field without writing it, so deletion can happen immediately before or after
the theme rollout without exposing a machine field to shoppers.

Customer sync already filters the legacy attribute titles, so no new
`easystore_attr_click_id` values are written to HubSpot.

### 5. GitHub Environment credentials

`prod` and `dev` need:

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

Optional variables:

```text
ORDER_ATTRIBUTION_WINDOW_DAYS=30
ACQUISITION_ATTRIBUTION_WINDOW_DAYS=30
```

The Cloudflare token needs D1 read access for attribution. The HubSpot token needs
Order/Contact read-write plus the relevant schema scopes because the jobs provision
`cc_order_*` / `cc_acquisition_*` properties.

## Production smoke test

Use one customer and two different tracked platforms.

1. Open:

   ```text
   https://go.cardboard.sg/wa?campaign=tracking-test&content=message-a&to=/
   ```

2. Confirm the redirect includes WhatsApp UTMs and a `cb_click_id`.
3. Sign in and browse one storefront page so `/touch` can bind the click.
4. Place Order A.
5. Run **Sync order source attribution** for `prod`.
6. Confirm Order A has:

   ```text
   cc_order_source=whatsapp
   cc_order_campaign=tracking-test
   cc_order_content=message-a
   cc_order_attribution_status=attributed
   ```

7. Open a Facebook tracked link with a different content value:

   ```text
   https://go.cardboard.sg/fb?campaign=tracking-test&content=post-b&to=/
   ```

8. Place Order B and rerun attribution.
9. Confirm:

   ```text
   Order A = whatsapp
   Order B = facebook
   Contact acquisition = unchanged
   ```

10. Confirm neither Order nor Contact has a newly written Click-ID attribution
    property.

## Reporting

Order revenue can be grouped/summed by:

- `cc_order_source`
- `cc_order_campaign`
- `cc_order_content`
- source + campaign
- campaign + content

Contact acquisition reports use `cc_acquisition_*` instead. Keep the two property
families separate unless a report explicitly compares acquisition versus later
conversion behavior.

## Known limits

- Touch history starts when `customer_touches` goes live. Old Orders cannot be
  deterministically reconstructed from browser state that was never recorded.
- An untracked external link has no D1 click and cannot receive deterministic
  source attribution from this model.
- Cross-device journeys are not deterministic unless the touch is bound to the
  customer on the device that holds it.
- Browser JavaScript/storage blocking can prevent touch binding.
- `no_recent_tracked_touch` is not synonymous with `direct`.

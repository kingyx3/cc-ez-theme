# Order source attribution

This is the operating guide for deterministic **per-order marketing source** tracking.

It is intentionally separate from customer acquisition attribution:

- **Contact acquisition** answers: which tracked click acquired this account?
- **Order source** answers: which tracked marketing touch most recently led this customer back to the store before this purchase?

A repeat customer can therefore have different sources on different Orders without changing the Contact's original acquisition source.

## Attribution model

The Order model is **last tracked human touch before the Order**, with a fixed default lookback window of **30 days**.

A touch can attribute an EasyStore Order only when it:

1. exists in Cloudflare D1 `source_clicks`;
2. is human traffic (`bot = 0`);
3. was bound to the same EasyStore `customer_id`;
4. happened before the Order creation timestamp; and
5. is no older than 30 days, unless `ORDER_ATTRIBUTION_WINDOW_DAYS` is intentionally changed later.

There is **no fallback to the Contact acquisition source**. If no qualifying tracked touch exists, the Order is reported as `no_recent_tracked_touch` instead of inventing a source.

Example:

| Time | Event | Attribution result |
| --- | --- | --- |
| 1 Aug | Facebook tracked link, customer signs up | Contact acquisition = Facebook |
| 10 Aug | Purchase | Order A = Facebook if that touch is still eligible |
| 20 Aug | WhatsApp tracked link | latest tracked touch = WhatsApp |
| 21 Aug | Purchase | Order B = WhatsApp |
| 23 Aug | Instagram tracked link | latest tracked touch = Instagram |
| 24 Aug | Purchase | Order C = Instagram |

Each Order keeps its own snapshot.

## Data flow

```text
marketing link
    ↓
go.cardboard.sg / cc-attribution Worker
    ↓
source_clicks (D1)
    ↓ cb_click_id + UTMs
EasyStore storefront
    ↓
logged-in EasyStore customer + latest click id
    ↓
customer_touches (D1, append-only)
    ↓
EasyStore Order customer_id + created_at
    ↓
cloudflare_hubspot_order_attribution.py
    ↓
HubSpot Order cc_order_*
```

The existing EasyStore customer `Click ID` attribute remains write-once for Contact acquisition. The browser's current `cb_click_id` is refreshed by later tracked campaign visits and is used for per-Order touch history.

## Marketing URLs

Campaigns and posts **do not need to be predefined in code**.

Use:

```text
https://go.cardboard.sg/<platform>?campaign=<campaign>&content=<content>&to=<store-path>
```

Example:

```text
https://go.cardboard.sg/fb?campaign=rf&content=grp-aug26&to=/collections/reality-fracture
```

The Worker generates:

```text
utm_source=facebook
utm_medium=social
utm_campaign=rf
utm_content=grp-aug26
cb_click_id=<new UUID>
```

### Supported platform codes

| Code | Source | Medium |
| --- | --- | --- |
| `fb` | `facebook` | `social` |
| `ig` | `instagram` | `social` |
| `tt` | `tiktok` | `social` |
| `wa` | `whatsapp` | `messaging` |
| `ca` | `carousell` | `marketplace` |
| `em` | `email` | `email` |
| `qr` | `qr` | `offline` |

Campaign and content values are dynamic. A new campaign does not require a PR or Worker deployment.

A completely new platform/source code does require adding one entry to `CHANNELS` in `cloudflare/attribution-worker/src/index.js`. This keeps reporting names canonical.

### Campaign/content naming

Use short, stable, lowercase labels.

Recommended split:

- `campaign`: initiative/product/launch, e.g. `rf`, `restock`, `one-piece`
- `content`: exact post/ad/message, e.g. `grp-aug26`, `retarget-01`, `vip-blast`

Examples:

```text
https://go.cardboard.sg/fb?campaign=one-piece&content=launch-post&to=/collections/one-piece
https://go.cardboard.sg/ig?campaign=one-piece&content=reel-01&to=/collections/one-piece
https://go.cardboard.sg/wa?campaign=one-piece&content=vip-group&to=/collections/one-piece
```

Do not create one Worker alias per campaign/post. `/rf` and `/rf-bump` are intentionally retired; use the generic URL format instead.

### Destination paths

`to` is optional. If omitted, the link lands on the storefront home page.

Only a relative store path beginning with `/` is accepted. Absolute URLs, protocol-relative URLs, and backslash forms are rejected so `go.cardboard.sg` cannot become an open redirect.

## HubSpot Order properties

The Order attribution job provisions/writes:

| Property | Meaning |
| --- | --- |
| `cc_order_source` | source selected for this Order |
| `cc_order_medium` | medium selected for this Order |
| `cc_order_campaign` | campaign label |
| `cc_order_content` | exact post/ad/message label |
| `cc_order_click_id` | immutable selected Cloudflare click UUID |
| `cc_order_touch_at` | selected click timestamp |
| `cc_order_attribution_model` | `last_tracked_touch` |
| `cc_order_attribution_window_days` | normally `30` |
| `cc_order_attribution_status` | attribution result/status |

`hs_source_store` remains the commerce storefront and `easystore_order_channel` remains the sales channel EasyStore reports. Neither is repurposed as marketing attribution.

If an Order already contains a different `cc_order_click_id`, the job reports a conflict and refuses to overwrite the historical snapshot.

## Storefront touch binding

`theme/snippets/attribution-click-id.liquid` runs globally.

When EasyStore exposes a logged-in `customer.id`, the browser sends only:

```json
{
  "customer_id": "12345",
  "click_id": "<UUID>"
}
```

to `https://go.cardboard.sg/touch`.

No name, email, phone, or profile fields are sent. The Worker only accepts click IDs already present in `source_clicks` and excludes tracked bot traffic. `customer_touches` is append-only and `(customer_id, click_id)` is unique, so retries cannot move the original binding timestamp forward.

If a shopper lands while logged out, the click remains in browser storage. After registration/sign-in, the next storefront page can bind that click to the EasyStore customer.

## D1 migration and deployment ordering

Migration `0003_order_source_attribution.sql` adds:

- `source_clicks.content`
- `customer_touches`
- indexes used by the Order attribution lookup

All schema changes are applied through Wrangler's D1 migration system, not by manually executing the SQL file. Wrangler records applied migration filenames in its migration ledger and only applies unapplied migrations.

The Worker deployment workflow enforces this order:

```text
validate Worker/tests
    ↓
apply pending D1 migrations
    ↓
run migration command again to prove rerun is a no-op
    ↓
deploy cc-attribution
```

The PR validation job also creates a fresh local D1 database and runs the complete migration set twice. Therefore rerunning CI/CD is safe and an already-applied migration is not executed again.

Do not deploy the new Worker code manually before the migration has succeeded.

## Handing go.cardboard.sg from cc-rf to cc-attribution

`go.cardboard.sg` is a Cloudflare Worker **Custom Domain**. Only the Worker that owns that Custom Domain receives all paths on that hostname.

The target state is:

```text
go.cardboard.sg
    → cc-attribution
```

The EasyStore apex (`cardboard.sg`) and `www` records do not need to be changed for this handoff.

### Recommended handoff

1. In Cloudflare Dashboard, open **Workers & Pages**.
2. Open the temporary **cc-rf** Worker.
3. Go to **Settings → Domains & Routes**.
4. Find the Custom Domain `go.cardboard.sg` and remove/delete that Custom Domain from `cc-rf`.
5. Do **not** delete or alter `cardboard.sg` or `www.cardboard.sg` DNS records.
6. Once `go.cardboard.sg` is no longer attached to `cc-rf`, deploy `cc-attribution` from this repository. Its `wrangler.jsonc` contains:

   ```json
   {
     "pattern": "go.cardboard.sg",
     "custom_domain": true
   }
   ```

7. Wrangler/Cloudflare will attach `go.cardboard.sg` to `cc-attribution` and manage the hostname's Worker DNS/certificate relationship.
8. Verify:

   ```text
   https://go.cardboard.sg/health
   ```

   Expected response identifies `cc-attribution`.
9. Verify a real generic tracking URL redirects correctly and produces a `cb_click_id`.
10. After the new Worker is confirmed live, the old `cc-rf` Worker can be deleted if it has no other domains/routes or purpose.

You do **not** need to delete `cc-rf` before the handoff. Removing its `go.cardboard.sg` Custom Domain is sufficient. Keeping it temporarily is safer because you can inspect/recover it during cutover. Delete the Worker itself only after `cc-attribution` is verified.

Cloudflare may leave the old automatically generated Advanced Certificate visible after deleting a Custom Domain. It does not affect functionality; it can be removed separately later if desired for certificate inventory cleanup.

## GitHub Environment requirements

The `prod` and `dev` environments need:

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

Optional override:

```text
ORDER_ATTRIBUTION_WINDOW_DAYS=30
```

The Cloudflare token needs D1 read access for the Order attribution job and deployment/migration permissions for the Worker deployment workflow. The HubSpot token needs Order read/write and CRM schema read/write because the job provisions `cc_order_*` fields when needed.

## Production smoke test

After the D1 migration, Worker handoff, and theme deployment:

1. Open:

   ```text
   https://go.cardboard.sg/wa?campaign=tracking-test&content=message-a&to=/
   ```

2. Confirm the redirect includes `utm_source=whatsapp`, `utm_medium=messaging`, the expected campaign/content, and a UUID `cb_click_id`.
3. Sign in/register if needed, then browse a storefront page so the `/touch` request can bind the click to the customer.
4. Place Order A.
5. Run **Sync order source attribution** for `prod`.
6. Confirm Order A has `cc_order_source=whatsapp` and the matching campaign/content/click ID.
7. Open a Facebook tracked URL with a different `content` value and place Order B.
8. Rerun attribution.
9. Confirm Order A is still WhatsApp while Order B is Facebook.
10. Confirm the Contact acquisition fields did not change merely because Order B had a later touch.

## Known limits

- Touch history starts when this rollout goes live; historical Orders cannot be reconstructed deterministically from browser state that was never recorded.
- Untracked external links do not create deterministic D1 touches.
- Cross-device journeys are not deterministic unless the tracked click is later bound on the purchasing device/session.
- A browser blocking JavaScript/storage can prevent touch binding.
- `no_recent_tracked_touch` should not be relabelled `direct` without separate evidence.

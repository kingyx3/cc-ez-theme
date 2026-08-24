# Creating marketing links

Use `go.cardboard.sg` for every tracked marketing link. The Worker records the
source click, adds UTMs, generates the internal `cb_click_id`, and redirects the
shopper to the requested storefront path.

## URL format

```text
https://go.cardboard.sg/<platform>?campaign=<campaign>&content=<content>&to=<store-path>
```

Example:

```text
https://go.cardboard.sg/fb?campaign=rf&content=fb-main&to=/collections/reality-fracture
```

That redirects to the Reality Fracture collection with:

```text
utm_source=facebook
utm_medium=social
utm_campaign=rf
utm_content=fb-main
cb_click_id=<internal Worker UUID>
```

## Create a new link

1. Pick the platform code.
2. Pick a short stable `campaign` label for the launch/product/initiative.
3. Pick a `content` label for the exact ad, post, message, QR placement, or creative.
4. Set `to` to the storefront path the shopper should land on.
5. Open the finished URL once and confirm it redirects to the expected page.

No Worker deploy is needed for a new campaign, content label, or destination path.
A code change is only needed when adding a new platform/source code.

## Supported platform codes

| Code | Source | Medium |
| --- | --- | --- |
| `fb` | `facebook` | `social` |
| `ig` | `instagram` | `social` |
| `tt` | `tiktok` | `social` |
| `wa` | `whatsapp` | `messaging` |
| `ca` | `carousell` | `marketplace` |
| `em` | `email` | `email` |
| `qr` | `qr` | `offline` |

## Naming convention

Keep `campaign` and `content` lowercase and stable. Use letters, numbers, dots,
underscores, or hyphens. The Worker normalizes other characters.

Recommended examples:

```text
campaign=rf
campaign=restock
campaign=one-piece

content=fb-main
content=grp-aug26
content=retarget-01
content=vip-blast
```

Use `campaign` for the thing being promoted and `content` for the exact marketing
placement. Different creatives should normally get different `content` values so
HubSpot Order reports can distinguish them.

## Destination paths

`to` must be a relative path on `cardboard.sg` beginning with `/`.

Home page:

```text
https://go.cardboard.sg/fb?campaign=rf&content=fb-main&to=/
```

Reality Fracture collection:

```text
https://go.cardboard.sg/fb?campaign=rf&content=fb-main&to=/collections/reality-fracture
```

Do not put a full external URL in `to`. Absolute URLs, protocol-relative URLs,
and backslash-based paths are rejected to prevent open redirects.

If the destination contains query parameters, URL-encode the entire `to` value
before inserting it into the tracking URL.

## One stable Reality Fracture Facebook link

For the main Facebook link to Reality Fracture, use:

```text
https://go.cardboard.sg/fb?campaign=rf&content=fb-main&to=/collections/reality-fracture
```

Reuse that URL when you intentionally want all general Facebook traffic grouped
under `content=fb-main`. Create a different `content` value when you want to
measure a particular ad/post separately.

## Examples by channel

Facebook:

```text
https://go.cardboard.sg/fb?campaign=rf&content=fb-main&to=/collections/reality-fracture
```

Instagram:

```text
https://go.cardboard.sg/ig?campaign=rf&content=ig-story-01&to=/collections/reality-fracture
```

WhatsApp:

```text
https://go.cardboard.sg/wa?campaign=rf&content=vip-group&to=/collections/reality-fracture
```

Email:

```text
https://go.cardboard.sg/em?campaign=rf&content=launch-email&to=/collections/reality-fracture
```

QR code:

```text
https://go.cardboard.sg/qr?campaign=rf&content=counter-card&to=/collections/reality-fracture
```

## Testing a new link

First confirm the Worker is public:

```text
https://go.cardboard.sg/health
```

Expected response:

```json
{"ok":true,"worker":"cc-attribution"}
```

Then open the marketing link and verify that it redirects to `cardboard.sg` with
`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, and a generated
`cb_click_id` in the destination URL.

The bare root `https://go.cardboard.sg/` intentionally returns `Not found` because
it has no source code and therefore must not create an unattributed marketing
click.

## Attribution behavior

The link only records the marketing click. When the shopper is authenticated on
the storefront, the theme binds the latest internal click ID to their EasyStore
customer ID in Cloudflare D1. Contact acquisition and per-order attribution then
resolve from that D1 touch history.

Click IDs are internal join keys only; do not create or maintain an EasyStore or
HubSpot Click ID field for marketing links.

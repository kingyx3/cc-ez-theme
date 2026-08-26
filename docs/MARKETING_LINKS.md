# Creating marketing links

Use `go.cardboard.sg` for tracked marketing links. The Worker records the source
click, preserves supported advertising-network click IDs, adds UTMs, generates
the internal `cb_click_id`, and redirects the shopper to the requested storefront
path on `cardboard.sg`.

## Which domain belongs in each platform?

The **business/website identity is always `https://cardboard.sg`**.

Use `https://cardboard.sg` for fields such as:

- Google Business Profile website
- Google Merchant Center / online store website
- Meta Business / Facebook Page website
- TikTok Business website
- LinkedIn Company Page website
- any verification, canonical, SEO, or public company website field

`go.cardboard.sg` is a first-party click router, not the public storefront. Use it
only where the platform asks for the URL that an ad/post/button should open and
you intentionally want that click tracked through Cloudflare.

For paid ads created manually, use the matching `go.cardboard.sg` URL as the ad
destination so the platform's click identifier reaches the Worker before the
redirect to `cardboard.sg`.

### Google Ads

Keep **auto-tagging enabled**. Do not manually create a `gclid`.

For a Google ad whose real landing page is
`https://cardboard.sg/collections/reality-fracture`, use a Final URL such as:

```text
https://go.cardboard.sg/gg?campaign=rf&content=google-search-01&to=/collections/reality-fracture
```

Google appends `gclid` (or, for some privacy-constrained traffic, `gbraid` /
`wbraid`) to the serving URL. The Worker preserves it and forwards it to the
`cardboard.sg` landing page.

Do **not** put the Cloudflare URL in Google Ads' Tracking template merely to run
this Worker. Google parallel tracking can load a tracking template separately
from the shopper's navigation, which would break the browser-bound
`cb_click_id` handoff. The shopper-facing Final URL is the correct place for this
first-party redirect.

### Google Business Profile and Merchant Center

For the Google Business Profile website and Merchant Center verified/claimed
website, use:

```text
https://cardboard.sg
```

Merchant Center product `link` values should remain the real
`https://cardboard.sg/...` product landing pages. Shopping-ad redirects are a
separate Merchant Center / Google Ads concern; do not replace the claimed store
website with `go.cardboard.sg`.

### Meta / Facebook / Instagram ads

Use the appropriate tracked destination:

```text
https://go.cardboard.sg/fb?campaign=rf&content=meta-ad-01&to=/collections/reality-fracture
```

or:

```text
https://go.cardboard.sg/ig?campaign=rf&content=ig-ad-01&to=/collections/reality-fracture
```

When Meta appends `fbclid`, the Worker preserves it and forwards it unchanged.

### TikTok ads

```text
https://go.cardboard.sg/tt?campaign=rf&content=tiktok-ad-01&to=/collections/reality-fracture
```

The Worker preserves `ttclid`.

### LinkedIn ads

```text
https://go.cardboard.sg/li?campaign=rf&content=linkedin-ad-01&to=/collections/reality-fracture
```

The Worker preserves `li_fat_id`.

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

If the incoming request contains a supported vendor click ID, that parameter is
also forwarded unchanged.

## Supported ad click parameters

| Incoming parameter | Network | HubSpot destination |
| --- | --- | --- |
| `gclid` | Google Ads | `hs_google_click_id` |
| `fbclid` | Meta/Facebook | `hs_facebook_click_id` |
| `ttclid` | TikTok | `hs_tiktok_click_id` |
| `li_fat_id` | LinkedIn | `hs_linkedin_click_id` |
| `gbraid` | Google Ads | retained in D1 / forwarded; not written as GCLID |
| `wbraid` | Google Ads | retained in D1 / forwarded; not written as GCLID |

The Worker preserves these identifiers case-sensitively. They are advertising
network identifiers, not the internal `cb_click_id`.

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
| `gg` | `google` | `cpc` |
| `fb` | `facebook` | `social` |
| `ig` | `instagram` | `social` |
| `tt` | `tiktok` | `social` |
| `li` | `linkedin` | `social` |
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
content=google-search-01
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

For an ad-network smoke test, add a harmless fake parameter yourself, for example:

```text
https://go.cardboard.sg/gg?campaign=tracking-test&content=manual&gclid=TEST-GCLID&to=/
```

The redirected `cardboard.sg` URL should still contain `gclid=TEST-GCLID`.

The bare root `https://go.cardboard.sg/` intentionally returns `Not found` because
it has no source code and therefore must not create an unattributed marketing
click.

## Attribution and conversion behavior

The Worker UUID and vendor IDs answer different questions:

- `cb_click_id` is an internal Cloudflare join key used to connect a browser
  touch to an EasyStore customer and then to Contact/Order attribution.
- `gclid`, `fbclid`, `ttclid`, and `li_fat_id` are vendor identifiers used to
  match HubSpot conversion events back to ad-network clicks.

When the shopper is authenticated, the theme binds the internal Worker click to
their EasyStore customer ID. The scheduled Cloudflare → HubSpot stage then:

1. keeps the existing immutable Contact acquisition snapshot;
2. independently finds the newest bound click for each supported ad network;
3. writes the vendor ID to HubSpot's native click-ID property when HubSpot exposes
   that native property as writable; and
4. stores a companion `cc_*_click_at` timestamp so older retries cannot replace a
   newer vendor ID.

Never copy `cb_click_id` into any HubSpot `hs_*_click_id` property.

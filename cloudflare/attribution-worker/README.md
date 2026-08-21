# Cloudflare attribution Worker

Layer 1 source tracking for `cardboard.sg`.

The Worker handles controlled entry URLs such as:

- `https://cardboard.sg/go/ca` — Carousell
- `https://cardboard.sg/go/fb` — Facebook
- `https://cardboard.sg/go/wa` — WhatsApp
- `https://cardboard.sg/go/qr` — QR / offline

A request gets a random `click_id`, is recorded in D1, is optionally mirrored to Workers Analytics Engine, and is redirected to the store with UTMs plus `cb_click_id` - both in the query string and in a first-party `cb_click_id` cookie.

This Worker deliberately stores no email, mobile number, IP address, EasyStore customer ID, or HubSpot contact ID. Customer identity remains authoritative in EasyStore and the existing CRM sync continues to join EasyStore customers to HubSpot by OTP-verified normalized mobile number.

The click id is carried onward by the storefront and joined to HubSpot contacts by a separate stage. See [docs/SOURCE_ATTRIBUTION.md](../../docs/SOURCE_ATTRIBUTION.md) for the whole chain; the boundary this Worker keeps is at the bottom of this file.

## The click cookie

The URL parameter dies at the first navigation, so the redirect also sets:

```text
cb_click_id=<uuid>; Domain=cardboard.sg; Path=/; Max-Age=7776000; SameSite=Lax; Secure
```

Ninety days is the window an offline QR code plausibly spans. Two deliberate choices:

- **Not `HttpOnly`.** `theme/snippets/attribution-click-id.liquid` has to read the value to fill the EasyStore customer attribute that carries it into the CRM. That is safe here because the value is an opaque random id: it holds no personal data and grants no access.
- **`Domain`, not host-only.** A host-only cookie set on `cardboard.sg` is not sent to `www.cardboard.sg`, which would lose the id for exactly the shoppers whose link or browser normalizes to the www host. The domain is derived from `STORE_URL` and can be overridden with a `COOKIE_DOMAIN` var.

The cookie is refreshed by every tracked click, so it is last touch. The storefront fills the customer attribute only when it is empty, so what lands on a customer is the click that was current when the account was created.

## Automated traffic

Pasting a `/go/wa` link into WhatsApp fetches it once to draw the preview card, and Facebook re-fetches a `/go/fb` link for impressions of the post. Those are not shoppers, and counting them inflates exactly the number this Worker exists to report.

Such a request is **recorded with the reason it was judged automated, never dropped**:

| `bot_reason` | Judged by |
| --- | --- |
| `verified-bot` | Cloudflare's own `cf.botManagement.verifiedBot` |
| `prefetch` | the browser's `Sec-Purpose` / `Purpose` / `X-Purpose` / `X-Moz` header |
| `user-agent` | a known crawler or HTTP client user agent |
| `no-user-agent` | no user agent at all |
| `` (empty) | an ordinary click |

Keeping the row means the raw count stays complete, a channel report can subtract what it chooses to, and a mistake in the user-agent list shows up in the data instead of silently deleting real traffic. Every count therefore has to say whether it includes automated requests - see the queries below.

A `prefetch` is the one to read carefully: a shopper's own browser may speculatively load a link before they tap it, so that request can be a real visit.

## Data shape

D1 stores one row per tracked GET request:

| field | example |
| --- | --- |
| `click_id` | UUID |
| `source` | `facebook` |
| `medium` | `social` |
| `campaign` | `always-on` |
| `path` | `/go/fb` |
| `country` | `SG` |
| `clicked_at` | Unix epoch milliseconds |
| `bot` | `0` for a click, `1` for automated traffic |
| `bot_reason` | `prefetch`, or empty for a click |

Analytics Engine uses the same meanings:

- `index1`: click ID
- `blob1`: source
- `blob2`: medium
- `blob3`: campaign
- `blob4`: entry path
- `blob5`: country
- `blob6`: why the request looked automated, or empty
- `double1`: `1`
- `double2`: `1` for automated traffic, `0` for a click

The Analytics Engine dataset is named `cc_source_clicks` and is created automatically on its first successful write.

## Cloudflare resources

`wrangler.jsonc` binds:

- `DB` → D1 database `cc-attribution`
- `ANALYTICS` → Analytics Engine dataset `cc_source_clicks`

The production D1 database UUID is committed in `wrangler.jsonc`. It is a resource identifier, not a credential. Cloudflare API credentials must never be committed. `scripts/cloudflare_hubspot_attribution.py` holds the same UUID so it can read the database, and `crm_tests/test_cloudflare_attribution.py` pins the two copies together.

`workers_dev` is **off**. A `*.workers.dev` hostname is a second, unrouted way to reach a Worker whose whole job is to mint click rows, so a click can only be recorded through the `cardboard.sg` route.

The Wrangler config also owns the route:

```text
cardboard.sg/go/*
```

The `cardboard.sg` DNS record must be proxied through Cloudflare for a Worker Route to execute.

## GitHub Actions deployment

`.github/workflows/deploy-cloudflare-attribution-worker.yml` deploys this Worker automatically when relevant files are pushed to `main`. A merged pull request that changes `cloudflare/attribution-worker/**` therefore triggers a production deployment. The workflow can also be run manually with `workflow_dispatch`.

A pull request that changes those files runs the `Validate Worker` job only: it never holds Cloudflare credentials and never deploys.

The deployment job:

1. installs the pinned Wrangler dependency;
2. validates the Worker JavaScript;
3. runs the Worker behaviour tests;
4. performs a Wrangler dry run;
5. applies pending remote D1 migrations;
6. deploys the `cc-attribution` Worker and its route/bindings.

Do not also enable Cloudflare Builds Git deployment for this Worker unless you intentionally want two independent deployment systems. GitHub Actions is the deployment source of truth for this repository.

### Required repository secrets

Add these under GitHub → repository **Settings → Secrets and variables → Actions → Repository secrets**:

- `CLOUDFLARE_ACCOUNT_ID` — the Cloudflare account that owns `cardboard.sg`, the Worker, and the D1 database.
- `CLOUDFLARE_API_TOKEN` — a scoped Cloudflare API token used only by CI.

The token needs enough access to:

- deploy/edit the Worker script;
- create/update the Worker route for `cardboard.sg`;
- apply D1 migrations to `cc-attribution`.

Scope the token to the single Cloudflare account and the `cardboard.sg` zone where possible. D1 migrations write to the database, so the token needs D1 edit/write access in addition to Worker deployment permissions.

## Local commands

From this directory:

```bash
npm install
npm run check
npm test
npm run d1:migrate:local
npm run dev
```

`npm run check` only parses the file. `npm test` runs `test/worker.test.js` against the real exported handler with fake bindings, and covers the redirect, the cookie, each channel mapping, the D1 row, automated-traffic flagging, a D1 outage, and every refusal path.

To intentionally operate against production Cloudflare resources, authenticate Wrangler first and then use:

```bash
npm run d1:migrate:remote
npm run deploy
```

## Analytics Engine enablement issue

The `ANALYTICS` binding is configured in `wrangler.jsonc` as:

```json
{
  "binding": "ANALYTICS",
  "dataset": "cc_source_clicks"
}
```

No blank dataset should be created manually.

If Cloudflare still rejects deployment with `You need to enable Analytics Engine` even though it is enabled at account level, temporarily remove the `analytics_engine_datasets` block and deploy with D1 only. The Worker checks for the binding before writing, so Layer 1 remains functional through D1 while the account entitlement is resolved. Re-add the binding afterwards.

## Test

After deployment:

```text
https://cardboard.sg/go/fb?campaign=test
```

should redirect to something equivalent to:

```text
https://cardboard.sg/?utm_source=facebook&utm_medium=social&utm_campaign=test&utm_content=fb&cb_click_id=<uuid>
```

Health endpoint:

```text
https://cardboard.sg/go/health
```

## Query D1

For a quick channel count, excluding link previews and prefetches:

```sql
SELECT source, COUNT(*) AS clicks
FROM source_clicks
WHERE bot = 0
GROUP BY source
ORDER BY clicks DESC;
```

For campaigns:

```sql
SELECT source, campaign, COUNT(*) AS clicks
FROM source_clicks
WHERE bot = 0
GROUP BY source, campaign
ORDER BY clicks DESC;
```

For how much of the raw total was automated:

```sql
SELECT source, bot_reason, COUNT(*) AS requests
FROM source_clicks
WHERE bot = 1
GROUP BY source, bot_reason
ORDER BY requests DESC;
```

Rows written before migration `0002` carry `bot = 0`, so a range spanning the deployment reports its older automated traffic as clicks.

## Attribution boundary

This is intentionally only Layer 1. It does not claim that a click belongs to a particular customer or order.

Order-level attribution should continue to come from a deterministic EasyStore signal (for example its referral / affiliate attribution). The existing GitHub Actions commerce sync can then write that order attribution into HubSpot while resolving the customer by normalized verified mobile number.

A future browser-to-customer binding should only be added when the identity handoff can be verified server-side. A browser-posted `customer_id` alone is not sufficient because a visitor can alter it.

That binding now exists, and it runs the other way round: the browser carries the Worker's own opaque `click_id` into an EasyStore customer attribute, and EasyStore - not the browser - remains the authority on who the customer is. A forged click id resolves to no D1 row and is counted as unresolved, so the worst a tampered value achieves is attributing one sign-up to somebody else's click. `docs/SOURCE_ATTRIBUTION.md` states the claim that chain is allowed to make, and its limits.

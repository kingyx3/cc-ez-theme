# Cloudflare attribution Worker

Layer 1 source tracking for `cardboard.sg`.

The Worker handles controlled entry URLs such as:

- `https://cardboard.sg/go/ca` — Carousell
- `https://cardboard.sg/go/fb` — Facebook
- `https://cardboard.sg/go/wa` — WhatsApp
- `https://cardboard.sg/go/qr` — QR / offline

A request gets a random `click_id`, is recorded in D1, is optionally mirrored to Workers Analytics Engine, and is redirected to the store with UTMs plus `cb_click_id`.

This Worker deliberately stores no email, mobile number, IP address, EasyStore customer ID, or HubSpot contact ID. Customer identity remains authoritative in EasyStore and the existing CRM sync continues to join EasyStore customers to HubSpot by OTP-verified normalized mobile number.

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

Analytics Engine uses the same meanings:

- `index1`: click ID
- `blob1`: source
- `blob2`: medium
- `blob3`: campaign
- `blob4`: entry path
- `blob5`: country
- `double1`: `1`

The Analytics Engine dataset is named `cc_source_clicks` and is created automatically on its first successful write.

## Before the first deployment

### 1. Add the real D1 database ID

`wrangler.jsonc` intentionally contains:

```text
REPLACE_WITH_D1_DATABASE_ID
```

Open the existing `cc-attribution` D1 database in Cloudflare and copy its database UUID, then replace that value. Do not connect Cloudflare Builds until this placeholder is replaced.

### 2. Install dependencies

From this directory:

```bash
npm install
```

### 3. Apply the D1 migration

```bash
npm run d1:migrate:remote
```

This creates `source_clicks` and its indexes.

### 4. Deploy

```bash
npm run deploy
```

The Wrangler config owns the route:

```text
cardboard.sg/go/*
```

The `cardboard.sg` DNS record must be proxied through Cloudflare for a Worker Route to execute.

## Connect the existing Worker to GitHub

In Cloudflare:

1. Workers & Pages → `cc-attribution`.
2. Settings → Builds → Connect.
3. Choose GitHub and repository `kingyx3/cc-ez-theme`.
4. Production branch: `main`.
5. Root directory: `cloudflare/attribution-worker`.
6. Deploy command: `npx wrangler deploy` (the Cloudflare default is fine).

The Worker name in Cloudflare must exactly match `name` in `wrangler.jsonc` (`cc-attribution`). If the manually created dashboard Worker has a different name, change the config before connecting Builds.

After GitHub is connected, treat `wrangler.jsonc` and `src/index.js` as the source of truth rather than editing the Worker in the dashboard.

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

For a quick channel count:

```sql
SELECT source, COUNT(*) AS clicks
FROM source_clicks
GROUP BY source
ORDER BY clicks DESC;
```

For campaigns:

```sql
SELECT source, campaign, COUNT(*) AS clicks
FROM source_clicks
GROUP BY source, campaign
ORDER BY clicks DESC;
```

## Attribution boundary

This is intentionally only Layer 1. It does not claim that a click belongs to a particular customer or order.

Order-level attribution should continue to come from a deterministic EasyStore signal (for example its referral / affiliate attribution). The existing GitHub Actions commerce sync can then write that order attribution into HubSpot while resolving the customer by normalized verified mobile number.

A future browser-to-customer binding should only be added when the identity handoff can be verified server-side. A browser-posted `customer_id` alone is not sufficient because a visitor can alter it.

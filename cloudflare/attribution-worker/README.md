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

## Cloudflare resources

`wrangler.jsonc` binds:

- `DB` → D1 database `cc-attribution`
- `ANALYTICS` → Analytics Engine dataset `cc_source_clicks`

The production D1 database UUID is committed in `wrangler.jsonc`. It is a resource identifier, not a credential. Cloudflare API credentials must never be committed.

The Wrangler config also owns the route:

```text
cardboard.sg/go/*
```

The `cardboard.sg` DNS record must be proxied through Cloudflare for a Worker Route to execute.

## GitHub Actions deployment

`.github/workflows/deploy-cloudflare-attribution-worker.yml` deploys this Worker automatically when relevant files are pushed to `main`. A merged pull request that changes `cloudflare/attribution-worker/**` therefore triggers a production deployment. The workflow can also be run manually with `workflow_dispatch`.

The deployment job:

1. installs the pinned Wrangler dependency;
2. validates the Worker JavaScript;
3. performs a Wrangler dry run;
4. applies pending remote D1 migrations;
5. deploys the `cc-attribution` Worker and its route/bindings.

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
npm run d1:migrate:local
npm run dev
```

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

# EasyStore → Slack webhook Worker

Cloudflare Worker that accepts EasyStore webhook POSTs, verifies the EasyStore HMAC signature, normalizes order-like payloads, and posts a Slack Block Kit notification.

The Worker is intentionally tolerant about payload shape because this repository does not yet have a captured EasyStore order webhook. Once a real payload is available, tighten the field mapping and add it as a fixture.

## Endpoints

- `GET /health` — health check.
- `POST /webhooks/easystore` — EasyStore webhook receiver.

## Required secrets

Never put either value in `wrangler.jsonc` or commit them to Git.

```bash
cd cloudflare/easystore-slack-worker
npm install

npx wrangler secret put SLACK_WEBHOOK_URL
npx wrangler secret put EASYSTORE_APP_SECRET
```

- `SLACK_WEBHOOK_URL`: Slack Incoming Webhook URL for the target channel.
- `EASYSTORE_APP_SECRET`: EasyStore app shared secret used to verify `EasyStore-Hmac-SHA256`.

## Optional configuration

`wrangler.jsonc` contains safe non-secret defaults:

- `STORE_LABEL`: label shown when a shop domain is unavailable.
- `MAX_BODY_BYTES`: maximum accepted webhook body size. Default: 262144 (256 KiB).
- `SLACK_TIMEOUT_MS`: maximum time to wait for Slack before returning an error to EasyStore. Default: 7000.

Optional environment variables you can add to `vars`:

- `ALLOWED_TOPICS`: comma-separated exact topic names. Leave unset to accept all verified EasyStore topics.
- `ORDER_URL_TEMPLATE`: HTTPS template for a "View order" button. Supported placeholders are `{id}`, `{order_number}`, and `{shop}`. Leave unset until the correct EasyStore admin URL is known.

Example:

```jsonc
"vars": {
  "STORE_LABEL": "Cardboard",
  "MAX_BODY_BYTES": "262144",
  "SLACK_TIMEOUT_MS": "7000",
  "ALLOWED_TOPICS": "order/create,order/paid",
  "ORDER_URL_TEMPLATE": "https://admin.example.com/orders/{id}"
}
```

Do not copy the example topic names or admin URL blindly. Confirm the topic strings and order URL format in your EasyStore setup first.

## Deploy

```bash
cd cloudflare/easystore-slack-worker
npm install
npm test
npm run check
npx wrangler deploy
```

The repository also includes `.github/workflows/deploy-cloudflare-easystore-slack-worker.yml`. Pull requests validate the Worker and run a Wrangler dry-run; pushes to `main` deploy using the repository's `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets. Worker secrets (`SLACK_WEBHOOK_URL` and `EASYSTORE_APP_SECRET`) still need to be set once on the deployed Worker.

Wrangler will print the deployed `workers.dev` hostname. Configure EasyStore to POST to:

```text
https://<your-worker>.<your-subdomain>.workers.dev/webhooks/easystore
```

EasyStore requires a public HTTPS endpoint and expects `200 OK` within 10 seconds. This Worker waits up to 7 seconds for Slack; a Slack failure returns `502` so EasyStore can treat the delivery as failed instead of silently dropping the notification.

## Slack setup

Create or use a Slack app with Incoming Webhooks enabled, add a webhook for the target channel, and store the generated URL as the `SLACK_WEBHOOK_URL` Worker secret.

Do not paste the Slack Incoming Webhook URL directly into EasyStore: EasyStore and Slack use different JSON payload formats.

## EasyStore setup

Register the deployed Worker URL for the order-related EasyStore events you want to receive, for example order created, paid, cancelled, refunded, and fulfilment updates where those events are available in your EasyStore app/admin configuration.

EasyStore signs each request using the app shared secret. The Worker verifies the raw request bytes against the `EasyStore-Hmac-SHA256` / `Easystore-Hmac-Sha256` header before parsing or forwarding anything.

If you configure `ALLOWED_TOPICS`, first observe the exact `Easystore-Topic` header values in Cloudflare Workers logs and then add only the exact topics you need.

## Safe logging

The Worker logs only metadata needed for troubleshooting: request ID, topic, shop domain, order ID/number, and Slack HTTP status. It deliberately does not log the full webhook payload, customer name, addresses, emails, or the Slack webhook URL.

## Local signed test

Set a throwaway local secret in `.dev.vars` (do not commit the file):

```dotenv
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
EASYSTORE_APP_SECRET=test-secret
```

Run:

```bash
npm run dev
```

In another shell:

```bash
BODY='{"order":{"id":12345,"order_number":"TEST-1001","currency_code":"SGD","total_price":"42.90","financial_status":"paid","customer":{"first_name":"Test","last_name":"Customer"},"line_items":[{"title":"Mailer Box","quantity":2}]}}'
SIG="$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac 'test-secret' -hex | awk '{print $2}')"

curl -i \
  -X POST \
  -H 'content-type: application/json' \
  -H "EasyStore-Hmac-SHA256: $SIG" \
  -H 'Easystore-Topic: order/create' \
  --data "$BODY" \
  http://localhost:8787/webhooks/easystore
```

Expected response:

```json
{"ok":true}
```

## When the first real webhook arrives

Use Cloudflare logs to confirm the topic/order metadata. If the Slack message is missing a field, capture a redacted sample payload (remove customer/address/contact data) and add a test fixture before tightening `normalizeEvent()`.

## Design notes

- HMAC is computed over the original raw request bytes.
- HMAC comparison uses Cloudflare's timing-safe crypto API.
- Request bodies are capped before JSON parsing.
- Secrets are Worker secrets, never source/config values.
- Slack has a bounded timeout so EasyStore can receive a response inside its webhook deadline.
- The top-level Slack `text` field is always populated so mobile/desktop notifications have a useful fallback.

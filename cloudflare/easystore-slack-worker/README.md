# EasyStore → Slack webhook Worker

Cloudflare Worker that receives EasyStore webhooks, verifies the EasyStore HMAC signature, normalizes supported events, and forwards a useful notification to Slack.

The normalizers are intentionally tolerant because the repository still does not contain real captured EasyStore payload fixtures. Once real events are available, add redacted fixtures and tighten the field mappings where needed.

## Endpoints

- `GET /health` — health check, including supported-topic count and Slack delivery mode.
- `POST /webhooks/easystore` — EasyStore webhook receiver.

## Supported EasyStore topics

The Worker explicitly supports and the default Wrangler configuration allowlists these topics:

```text
app/uninstall
store/update
product/create
product/update
product/delete
customer/create
customer/delete
order/create
order/update
order/paid
order/cancel
order/partially_paid
fulfillment/create
fulfillment/update
fulfillment/cancel
refund/create
channel/inventory_update
```

Unknown topics are acknowledged with `200 OK` but ignored rather than forwarded to Slack.

## Event-specific Slack content

The Worker produces event-specific headings and fields instead of treating every payload as an order:

- app uninstall: app/store/status
- store update: store ID/domain/status
- product events: title, product ID, SKU, price, inventory, status
- customer events: customer name and ID
- order events: order number, total, paid/due amounts, payment/fulfilment state, customer, delivery, line items
- fulfilment events: order, fulfilment ID/status, carrier/tracking, customer, line items
- refund create: order, refund ID, amount, reason/status
- inventory update: product, SKU, quantity, location/channel, resource ID

The Worker avoids logging full webhook bodies or customer contact/address data.

## Required Worker secrets

Never put either value in `wrangler.jsonc` or commit them to Git.

```bash
cd cloudflare/easystore-slack-worker
npm install

npx wrangler secret put SLACK_WEBHOOK_URL
npx wrangler secret put EASYSTORE_APP_SECRET
```

- `EASYSTORE_APP_SECRET`: EasyStore app shared secret used to verify `EasyStore-Hmac-SHA256`.
- `SLACK_WEBHOOK_URL`: either a Slack app Incoming Webhook URL (`https://hooks.slack.com/services/...`) or a Slack Workflow Builder webhook trigger URL (`https://hooks.slack.com/triggers/...`), depending on `SLACK_MODE`.

## Slack delivery modes

### Option A — direct Incoming Webhook (default)

`wrangler.jsonc` defaults to:

```jsonc
"SLACK_MODE": "incoming_webhook"
```

Create a Slack app Incoming Webhook for the target channel and store that URL in `SLACK_WEBHOOK_URL`.

The Worker itself creates the final Slack Block Kit message. The channel is selected when the Incoming Webhook is installed/created in Slack; app-based Incoming Webhooks do not support changing the destination channel per message.

Use this mode when all EasyStore notifications should go to one Slack channel and you want richer Block Kit formatting.

### Option B — Slack Automation / Workflow Builder

Use this mode if you want the destination channel and message template to be managed from Slack's Automation/Workflow Builder UI.

Change:

```jsonc
"SLACK_MODE": "workflow"
```

Then create a Slack workflow that starts **From a webhook** and define these eight text variables exactly:

```text
topic
title
store
resource
details
order_number
amount
url
```

The Worker always sends all eight keys as flat strings because Slack Workflow Builder webhook variables do not support nested JSON.

A recommended workflow is:

1. Trigger: **From a webhook**.
2. Add the eight variables above as `text` variables.
3. Add step: **Send a message to a channel**.
4. Choose the Slack channel you want, for example `#easystore-events` or `#orders`.
5. Suggested message template:

```text
{title}
{details}

Event: {topic}
Store: {store}
```

Optionally include:

```text
Order: {order_number}
Amount: {amount}
URL: {url}
```

6. Publish the workflow and copy the generated `https://hooks.slack.com/triggers/...` URL.
7. Replace the Worker secret with that workflow URL:

```bash
npx wrangler secret put SLACK_WEBHOOK_URL
```

For one destination channel, one workflow is enough for all 17 EasyStore topics. If you want different channels by event family, use separate Slack workflows/webhook URLs or add conditional branches in Workflow Builder; that would require either routing to multiple webhook secrets in this Worker or handling the branch logic inside Slack.

Note: Slack webhook-triggered workflows are rate limited more tightly than a simple message flow, so direct Incoming Webhooks are preferable if `channel/inventory_update` can generate bursts.

## Wrangler configuration

Safe non-secret defaults are in `wrangler.jsonc`:

- `STORE_LABEL`: fallback store label.
- `MAX_BODY_BYTES`: maximum webhook body size, default 262144 (256 KiB).
- `SLACK_TIMEOUT_MS`: Slack request timeout, default 7000 ms.
- `SLACK_MODE`: `incoming_webhook` or `workflow`.
- `ALLOWED_TOPICS`: exact comma-separated allowlist of the 17 supported EasyStore topics.

Optional vars you can add:

- `ORDER_URL_TEMPLATE`: HTTPS template for a View order button. Supported placeholders: `{id}`, `{order_number}`, `{shop}`.
- `PRODUCT_URL_TEMPLATE`: HTTPS template for a View product button. Supported placeholders: `{id}`, `{shop}`.

Do not guess EasyStore admin URLs. Leave these unset until the correct URL patterns are known.

## Deploy

```bash
cd cloudflare/easystore-slack-worker
npm install
npm test
npm run check
npx wrangler deploy
```

The repository includes `.github/workflows/deploy-cloudflare-easystore-slack-worker.yml`. Pull requests validate the Worker and run a Wrangler dry-run; pushes to `main` deploy using the repository's `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets.

Worker secrets still need to be configured on the deployed Worker separately.

Configure all 17 EasyStore webhook subscriptions to POST to the same endpoint:

```text
https://<your-worker>.<your-subdomain>.workers.dev/webhooks/easystore
```

EasyStore requires a public HTTPS endpoint and expects `200 OK` within 10 seconds. This Worker waits at most 7 seconds for Slack and returns `502` if Slack delivery fails.

## EasyStore verification

Every received request is verified against the raw request bytes using the EasyStore app secret and the `EasyStore-Hmac-SHA256` header before the JSON is parsed or sent to Slack.

## Local signed test

Set local secrets in `.dev.vars` and do not commit that file:

```dotenv
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
EASYSTORE_APP_SECRET=test-secret
```

Run:

```bash
npm run dev
```

Example order event:

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

## When real payloads arrive

Use Cloudflare logs to confirm topic/resource metadata. If a Slack notification is missing useful fields, capture a **redacted** payload fixture (remove addresses, emails, phone numbers, tokens, and other unnecessary customer data), add it to tests, and tighten the relevant normalizer.

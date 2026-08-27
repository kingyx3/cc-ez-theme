# EasyStore → Slack webhook Worker

Production-oriented Cloudflare Worker that receives EasyStore webhooks, verifies EasyStore HMAC signatures, normalizes the supported events, durably enqueues notifications with Cloudflare Queues, and delivers them to Slack with retry/backoff and rate-limit pacing.

## Architecture

```text
EasyStore
  │ HTTPS POST + HMAC
  ▼
Cloudflare Worker /webhooks/easystore
  │ verify + normalize + enqueue
  ▼
cc-easystore-slack-events (Cloudflare Queue)
  │ one-message batches, max concurrency 1
  ▼
Same Worker queue consumer
  │ Slack rate pacing + retry/backoff
  ▼
Slack Incoming Webhook or Workflow Builder

Repeated failures → cc-easystore-slack-dlq
```

The HTTP webhook path does **not** wait for Slack. It returns `200 OK` only after Cloudflare confirms the normalized event has been written to the queue. This keeps the EasyStore acknowledgement path short while making Slack delivery retryable.

Cloudflare Queues provide at-least-once delivery. A rare duplicate Slack notification is therefore still possible if Slack accepts a message but the queue acknowledgement is interrupted. Each event has a deterministic Event ID included in logs and Slack context/details to make duplicates diagnosable.

## Supported EasyStore topics

Exactly these topics are accepted by default:

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

Unknown topics are acknowledged with `200` and `ignored: true` so an accidental subscription does not create a retry storm.

## Endpoints

- `GET /health` — liveness only; returns `200` when the Worker code is running.
- `GET /ready` — configuration readiness; returns `503` if required secrets, Queue binding, Slack mode, or Slack URL are invalid.
- `POST /webhooks/easystore` — EasyStore webhook receiver.

The webhook endpoint accepts `application/json`, caps request bodies at 1 MiB by default, verifies `EasyStore-Hmac-SHA256` / `Easystore-Hmac-Sha256` against the raw body, and supports the hexadecimal format documented for EasyStore webhooks plus base64 for compatibility with other EasyStore developer examples.

## Required Cloudflare Worker secrets

Never commit these values or place them in `wrangler.jsonc`:

```bash
cd cloudflare/easystore-slack-worker
npm install

npx wrangler secret put EASYSTORE_APP_SECRET
npx wrangler secret put SLACK_WEBHOOK_URL
```

- `EASYSTORE_APP_SECRET` — EasyStore app shared secret used for HMAC verification.
- `SLACK_WEBHOOK_URL` — either a Slack Incoming Webhook URL or Workflow Builder webhook trigger URL, matching `SLACK_MODE`.

The Worker deliberately only permits Slack URLs on `https://hooks.slack.com` and validates the expected path:

- `SLACK_MODE=incoming_webhook` → `/services/...`
- `SLACK_MODE=workflow` → `/triggers/...`

This prevents a misconfigured secret from turning the Worker into an arbitrary outbound webhook relay.

## Cloudflare Queue resources

`wrangler.jsonc` binds:

- producer + consumer queue: `cc-easystore-slack-events`
- dead-letter queue: `cc-easystore-slack-dlq`

Consumer settings are intentionally conservative:

- one message per batch
- maximum consumer concurrency of one
- eight retries
- 30-second default retry delay
- exponential retry delay in code, capped at one hour
- `Retry-After` honored for Slack `429` responses

The GitHub Actions deployment workflow creates both queues if missing before deploying the Worker.

The repository's `CLOUDFLARE_API_TOKEN` must therefore have permissions sufficient to deploy Workers **and edit Queues**. `CLOUDFLARE_ACCOUNT_ID` must also be configured.

## Slack delivery modes

### Recommended for higher volume: Incoming Webhook

`wrangler.jsonc` defaults to:

```jsonc
"SLACK_MODE": "incoming_webhook"
```

Create a Slack app with Incoming Webhooks enabled, choose the destination channel when installing/adding the webhook, and save its `/services/...` URL as `SLACK_WEBHOOK_URL`.

Incoming Webhooks are conservatively paced slightly above one second per delivery. This is the preferred mode if `channel/inventory_update` can be noisy because Slack supports a higher sustained posting rate than webhook-triggered workflows.

### Slack Workflow Builder / Automations

To control message/channel routing in Slack, change:

```jsonc
"SLACK_MODE": "workflow"
```

Create a Slack Workflow that starts **From a webhook** and define these eight Text variables exactly:

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

Add a **Send a message to a channel** step and insert the variables you want. A sensible message is:

```text
{title}

{details}

Event: {topic}
Store: {store}
```

Use Slack's variable picker rather than typing braces literally.

The Worker uses conservative 6.5-second pacing in Workflow mode because Slack's current developer rate-limit table lists webhook workflow triggers at 10 per minute. This protects the workflow from bursts, but means a large inventory-event backlog can take time to drain. Prefer Incoming Webhook mode for high-volume notifications.

After publishing the Slack workflow, save its `https://hooks.slack.com/triggers/...` URL as `SLACK_WEBHOOK_URL`.

## EasyStore setup

Register the deployed Worker URL for all required topics:

```text
https://<worker-host>/webhooks/easystore
```

EasyStore requires a publicly reachable HTTPS URL with a valid certificate and expects `200 OK` within 10 seconds. It does not follow redirects for webhook delivery.

Do not use the Slack URL as the EasyStore webhook destination. EasyStore must call the Worker; the Worker then queues and sends to Slack.

## Non-secret configuration

`wrangler.jsonc` contains:

- `STORE_LABEL`: fallback store label.
- `MAX_BODY_BYTES`: request body cap; default `1048576` (1 MiB).
- `SLACK_TIMEOUT_MS`: per-Slack-request timeout; default `5000`.
- `SLACK_MODE`: `incoming_webhook` or `workflow`.
- `ALLOWED_TOPICS`: exact comma-separated allowlist containing the 17 supported topics.

Optional variables:

- `ORDER_URL_TEMPLATE`: HTTPS template for a View Order button. Placeholders: `{id}`, `{order_number}`, `{shop}`.
- `PRODUCT_URL_TEMPLATE`: HTTPS template for a View Product button. Placeholders: `{id}`, `{shop}`.

Example only—confirm the actual EasyStore admin routes before using templates:

```jsonc
"ORDER_URL_TEMPLATE": "https://admin.example.com/orders/{id}",
"PRODUCT_URL_TEMPLATE": "https://admin.example.com/products/{id}"
```

## Deployment

Pull requests run syntax validation, behavior tests, and a Wrangler deployment dry-run. Pushes to `main` repeat validation, ensure Queue resources exist, then deploy.

Manual validation:

```bash
cd cloudflare/easystore-slack-worker
npm install
npm run check
npm test
npx wrangler deploy --dry-run
```

Manual deployment:

```bash
npx wrangler queues info cc-easystore-slack-events || npx wrangler queues create cc-easystore-slack-events
npx wrangler queues info cc-easystore-slack-dlq || npx wrangler queues create cc-easystore-slack-dlq
npm run deploy
```

After deployment, check:

```text
GET https://<worker-host>/health  → 200
GET https://<worker-host>/ready   → 200
```

Then send one real EasyStore test event and confirm it appears in Slack.

## Operational behavior

### Slack outage or rate limiting

EasyStore requests continue to be accepted as long as Cloudflare Queue writes succeed. The queue consumer retries failed Slack calls with backoff and honors Slack's `Retry-After` header on `429`.

### Dead-letter queue

After the configured retry limit, Cloudflare places the message into `cc-easystore-slack-dlq` instead of silently discarding it. Inspect the DLQ in Cloudflare Queues when troubleshooting failed notifications. Do not attach an auto-acknowledging consumer to the DLQ unless you have another durable failure sink.

### Logging and privacy

Structured Worker logs contain operational metadata only: request/queue message IDs, deterministic event ID, topic, shop domain, resource type/ID, Slack status, attempt number, and retry delay. The Worker does **not** log:

- full EasyStore webhook bodies
- addresses or email addresses
- the Slack webhook URL
- the EasyStore app secret

The Queue contains the normalized event needed to render the Slack notification, not the raw EasyStore webhook body. Order/customer names may still be present when required for the notification itself.

### Large orders

Only the first 25 normalized line items are retained in the queue payload, while the original item count is kept for the `…and N more` indicator. This keeps Queue messages safely below Cloudflare's 128 KB message limit even when EasyStore sends a large order payload.

## Production checklist

Before enabling all 17 EasyStore webhooks:

1. Merge and deploy the Worker changes.
2. Confirm `cc-easystore-slack-events` and `cc-easystore-slack-dlq` exist in Cloudflare.
3. Set `EASYSTORE_APP_SECRET` and `SLACK_WEBHOOK_URL` as Worker secrets.
4. Confirm `/ready` returns `200`.
5. Choose `incoming_webhook` or `workflow` deliberately; use Incoming Webhook for higher event volume.
6. Register all 17 EasyStore topics against `/webhooks/easystore`.
7. Trigger at least one real order and one non-order event and verify Slack formatting.
8. Review Cloudflare Worker logs and Queue/DLQ metrics after launch.
9. Capture redacted real payload fixtures and tighten field mappings if EasyStore's actual payload differs from the tolerant mappings in `normalizeEvent()`.

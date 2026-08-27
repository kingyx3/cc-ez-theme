# EasyStore Slack Workflow template

This is the canonical Slack Workflow Builder presentation for the EasyStore webhook Worker when `SLACK_MODE=workflow`.

## Webhook trigger variables

Keep the existing eight **Text** variables on the Slack webhook trigger for backward compatibility with the Worker payload:

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

Do not print all eight variables in the Slack message. The Worker already folds the useful order/customer/payment context into `title` and `details`.

## Send a message step

Set the Slack Workflow Builder **Send a message to a channel** step to exactly:

```text
{title}

{details}
```

Use Slack's variable picker for `title` and `details`; do not type the braces literally.

Remove the old static lines:

```text
Topic: {topic}
Store: {store}
Resource: {resource}
Order: {order_number}
Amount: {amount}
{url}
```

Those fields remain in the webhook payload for compatibility and future routing, but they are intentionally not part of the human-facing notification.

## Expected notifications

An order creation should read like:

```text
🛍️ New order #1114 · SGD 168.00 · Unpaid

Customer: Bry Test 2
Items:
• MTG-FRA-SLB-EN × 1
```

EasyStore cancellation payloads can contain only the internal order ID. The Worker keeps a 30-day Durable Object correlation snapshot from richer order lifecycle events so a subsequent sparse cancellation can still read like:

```text
❌ Order #1114 cancelled · SGD 168.00

Customer: Bry Test 2
```

The internal EasyStore ID remains available in Worker/queue metadata but is not repeated in the human-facing message when correlation succeeds.

If the snapshot is missing, expired, or temporarily unavailable, notification delivery still proceeds with the explicit fallback instead of failing the EasyStore webhook:

```text
❌ Order cancelled · EasyStore ID 114410861

EasyStore order ID: 114410861
```

Correlation snapshots are keyed by store + EasyStore order ID and retain only the fields needed for lifecycle notifications: customer-facing order number, customer name, amount/currency, delivery method, and an HTTPS order URL when configured. They expire after 30 days.

## Workflow-mode notification policy

The Worker sends Slack Workflow notifications only for meaningful order lifecycle events:

```text
order/create
order/paid
order/partially_paid
order/cancel
fulfillment/create
fulfillment/cancel
refund/create
```

Other supported EasyStore events are still accepted and queued, but the workflow consumer acknowledges and logs them without triggering a Slack notification. This prevents stock/restock and generic update side-effects from flooding the channel.

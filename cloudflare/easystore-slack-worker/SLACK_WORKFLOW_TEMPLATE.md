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
🛍️ New order #1113 · SGD 208.00 · Unpaid

Customer: J T
Items:
• MTG-HOB-PBB-EN × 1
```

A cancellation with a human order number should read like:

```text
❌ Order #1113 cancelled · SGD 208.00
```

If EasyStore sends only its internal ID on the cancellation webhook, the Worker will instead make that explicit:

```text
❌ Order cancelled · EasyStore ID 114408393

EasyStore order ID: 114408393
```

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

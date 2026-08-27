import worker from "./index.js";

const MAX_QUEUE_STRING_LENGTH = 1000;
const MAX_QUEUE_ARRAY_ITEMS = 25;
const MAX_QUEUE_OBJECT_KEYS = 50;
const MAX_QUEUE_DEPTH = 8;

export const WORKFLOW_NOTIFICATION_TOPICS = Object.freeze([
  "order/create",
  "order/paid",
  "order/partially_paid",
  "order/cancel",
  "fulfillment/create",
  "fulfillment/cancel",
  "refund/create",
]);

const WORKFLOW_NOTIFICATION_TOPIC_SET = new Set(WORKFLOW_NOTIFICATION_TOPICS);

export default {
  fetch(request, env, ctx) {
    const queue = env.OUTBOUND_QUEUE;
    if (!queue?.send) return worker.fetch(request, env, ctx);

    const wrappedEnv = {
      ...env,
      OUTBOUND_QUEUE: {
        send(body, options) {
          const prepared = isWorkflowMode(env.SLACK_MODE)
            ? prepareWorkflowQueueMessage(body)
            : body;
          return queue.send(makeQueueSafeMessage(prepared), options);
        },
      },
    };
    return worker.fetch(request, wrappedEnv, ctx);
  },

  queue(batch, env, ctx) {
    if (!isWorkflowMode(env.SLACK_MODE)) return worker.queue(batch, env, ctx);

    const messages = [];
    for (const message of batch.messages) {
      const topic = normalizeTopic(message.body?.topic ?? message.body?.event?.topic);
      if (shouldDeliverWorkflowNotification(topic)) {
        messages.push(message);
        continue;
      }

      message.ack();
      console.log(JSON.stringify({
        event: "slack_workflow_notification_suppressed",
        queueMessageId: message.id,
        eventId: firstString(message.body?.eventId),
        topic: topic || null,
      }));
    }

    if (messages.length === 0) return undefined;
    return worker.queue({ messages }, env, ctx);
  },
};

export function shouldDeliverWorkflowNotification(topic) {
  return WORKFLOW_NOTIFICATION_TOPIC_SET.has(normalizeTopic(topic));
}

export function prepareWorkflowQueueMessage(message) {
  if (!message || typeof message !== "object" || Array.isArray(message)) return message;
  if (!message.event || typeof message.event !== "object" || Array.isArray(message.event)) return message;

  const topic = normalizeTopic(message.topic ?? message.event.topic);
  const event = message.event;
  const order = { ...(event.order ?? {}) };
  const resource = { ...(event.resource ?? {}) };

  order.number = normalizeWorkflowOrderNumber(order.number, order.id);

  if (resource.type === "order") {
    resource.name = order.number
      ? `Order ${order.number}`
      : (order.id ? `EasyStore order ${order.id}` : firstString(resource.name));
  } else if (order.number && ["fulfillment", "refund"].includes(resource.type) && /^order\s+#+/i.test(firstString(resource.name))) {
    resource.name = `Order ${order.number}`;
  }

  const preparedEvent = {
    ...event,
    topic,
    order,
    resource,
    eventId: "",
  };

  preparedEvent.heading = buildWorkflowHeading(topic, preparedEvent);
  preparedEvent.fields = buildWorkflowFields(topic, preparedEvent);

  return {
    ...message,
    topic,
    event: preparedEvent,
  };
}

export function makeQueueSafeMessage(message) {
  return boundQueueValue(message, 0);
}

function buildWorkflowHeading(topic, event) {
  const orderRef = firstString(event.order?.number);
  const orderId = firstString(event.order?.id, event.resource?.id);
  const total = formatMoney(event.order?.total, event.order?.currency);
  const paid = formatMoney(event.order?.paid, event.order?.currency);
  const refund = formatMoney(event.resource?.amount, event.resource?.currency);
  const payment = humanize(event.order?.paymentStatus);

  switch (topic) {
    case "order/create":
      return joinParts([
        orderRef ? `🛍️ New order ${orderRef}` : orderId ? `🛍️ New order · EasyStore ID ${orderId}` : "🛍️ New order",
        total,
        payment,
      ]);
    case "order/paid":
      return joinParts([
        orderRef ? `💰 Order ${orderRef} paid` : orderId ? `💰 Order paid · EasyStore ID ${orderId}` : "💰 Order paid",
        firstString(paid, total),
      ]);
    case "order/partially_paid":
      return joinParts([
        orderRef ? `💵 Order ${orderRef} partially paid` : orderId ? `💵 Order partially paid · EasyStore ID ${orderId}` : "💵 Order partially paid",
        paid,
      ]);
    case "order/cancel":
      return joinParts([
        orderRef ? `❌ Order ${orderRef} cancelled` : orderId ? `❌ Order cancelled · EasyStore ID ${orderId}` : "❌ Order cancelled",
        total,
      ]);
    case "fulfillment/create":
      return orderRef ? `📦 Fulfilment created · Order ${orderRef}` : "📦 Fulfilment created";
    case "fulfillment/cancel":
      return orderRef ? `📭 Fulfilment cancelled · Order ${orderRef}` : "📭 Fulfilment cancelled";
    case "refund/create":
      return joinParts([
        orderRef ? `↩️ Refund · Order ${orderRef}` : "↩️ Refund created",
        refund,
      ]);
    default:
      return firstString(event.heading, "EasyStore event");
  }
}

function buildWorkflowFields(topic, event) {
  const order = event.order ?? {};
  const resource = event.resource ?? {};

  switch (topic) {
    case "order/create":
      return compactFields([
        ["Customer", order.customer],
        ["Delivery", order.shippingMethod],
      ]);
    case "order/paid":
      return compactFields([
        ["Customer", order.customer],
        ["Delivery", order.shippingMethod],
      ]);
    case "order/partially_paid":
      return compactFields([
        ["Customer", order.customer],
        ["Paid", formatMoney(order.paid, order.currency)],
        ["Delivery", order.shippingMethod],
      ]);
    case "order/cancel":
      return compactFields([
        ["Customer", order.customer],
        ["EasyStore order ID", order.number ? "" : firstString(order.id, resource.id)],
      ]);
    case "fulfillment/create":
    case "fulfillment/cancel":
      return compactFields([
        ["Customer", order.customer],
        ["Carrier", resource.trackingCompany],
        ["Tracking", resource.trackingNumber],
      ]);
    case "refund/create":
      return compactFields([
        ["Customer", order.customer],
        ["Reason", resource.reason],
      ]);
    default:
      return Array.isArray(event.fields) ? event.fields : [];
  }
}

function normalizeWorkflowOrderNumber(number, id) {
  const raw = firstString(number);
  if (!raw) return "";

  const plain = raw
    .replace(/^order\s*/i, "")
    .replace(/^#+\s*/, "")
    .trim();
  if (!plain) return "";

  const normalizedId = firstString(id).replace(/^#+\s*/, "").trim();
  if (normalizedId && plain === normalizedId) return "";
  return `#${plain}`;
}

function compactFields(entries) {
  return entries
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => ({ label, value: String(value) }));
}

function formatMoney(value, currency) {
  if (value === undefined || value === null || value === "") return "";
  const raw = typeof value === "object"
    ? (value.amount ?? value.value ?? value.total)
    : value;
  if (raw === undefined || raw === null || raw === "") return "";

  const numeric = Number(raw);
  const rendered = Number.isFinite(numeric)
    ? new Intl.NumberFormat("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric)
    : String(raw);
  return [firstString(currency), rendered].filter(Boolean).join(" ");
}

function humanize(value) {
  if (!value) return "";
  return String(value)
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function joinParts(parts) {
  return parts.filter(Boolean).join(" · ");
}

function isWorkflowMode(value) {
  return normalizeTopic(value) === "workflow";
}

function normalizeTopic(value) {
  return firstString(value).toLowerCase();
}

function firstString(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

function boundQueueValue(value, depth) {
  if (value === null || value === undefined) return value ?? null;
  if (typeof value === "string") {
    return value.length <= MAX_QUEUE_STRING_LENGTH
      ? value
      : `${value.slice(0, MAX_QUEUE_STRING_LENGTH - 1)}…`;
  }
  if (["number", "boolean"].includes(typeof value)) return value;
  if (depth >= MAX_QUEUE_DEPTH) return "[truncated]";

  if (Array.isArray(value)) {
    return value
      .slice(0, MAX_QUEUE_ARRAY_ITEMS)
      .map((item) => boundQueueValue(item, depth + 1));
  }

  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .slice(0, MAX_QUEUE_OBJECT_KEYS)
        .map(([key, nested]) => [key, boundQueueValue(nested, depth + 1)]),
    );
  }

  return String(value).slice(0, MAX_QUEUE_STRING_LENGTH);
}

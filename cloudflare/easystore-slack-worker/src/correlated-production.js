import productionWorker, {
  makeQueueSafeMessage,
  prepareWorkflowQueueMessage,
} from "./production.js";
import {
  OrderCorrelation,
  correlateWorkflowOrder,
} from "./order-correlation.js";

export { OrderCorrelation };

const SHIPPING_CONTAINER_KEYS = new Set([
  "shipping_method",
  "shipping_methods",
  "shipping_method_name",
  "shipping_method_title",
  "shipping_title",
  "shipment_method",
  "shipping_line",
  "shipping_lines",
  "shipment",
  "shipments",
  "shipping",
  "shipping_option",
  "shipping_options",
  "shipping_rate",
  "shipping_rates",
  "delivery_method",
  "delivery_methods",
  "delivery_method_name",
  "delivery_option",
  "delivery_options",
  "courier",
  "courier_name",
  "pickup_method",
  "pickup_methods",
]);

const SHIPPING_LABEL_KEYS = [
  "title",
  "name",
  "label",
  "method",
  "method_name",
  "code",
  "courier",
  "courier_name",
  "provider",
  "shipping_method_name",
  "shipping_method_title",
  "shipping_name",
  "delivery_method_name",
  "delivery_name",
  "service_name",
  "service",
];

export default {
  fetch(request, env, ctx) {
    if (!isWorkflowMode(env.SLACK_MODE) || !env.OUTBOUND_QUEUE?.send) {
      return productionWorker.fetch(request, env, ctx);
    }

    const rawShippingMethod = readWorkflowShippingMethod(request);
    const queue = env.OUTBOUND_QUEUE;
    const wrappedEnv = {
      ...env,
      OUTBOUND_QUEUE: {
        async send(body, options) {
          const shippingMethod = await rawShippingMethod;
          const enriched = applyWorkflowShippingMethod(body, shippingMethod);
          const correlated = await correlateWorkflowOrder(enriched, env);
          const prepared = prepareWorkflowQueueMessage(correlated);
          return queue.send(makeQueueSafeMessage(prepared), options);
        },
      },
    };

    return productionWorker.fetch(request, wrappedEnv, ctx);
  },

  queue(batch, env, ctx) {
    return productionWorker.queue(batch, env, ctx);
  },
};

export function applyWorkflowShippingMethod(message, shippingMethod) {
  const method = firstString(shippingMethod);
  if (!method || !message?.event?.order || firstString(message.event.order.shippingMethod)) return message;

  return {
    ...message,
    event: {
      ...message.event,
      order: {
        ...message.event.order,
        shippingMethod: method,
      },
    },
  };
}

export function extractWorkflowShippingMethod(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "";

  const roots = [
    payload.order,
    payload.data?.order,
    payload.payload?.order,
    payload.data,
    payload.payload,
    payload,
  ];

  for (const root of roots) {
    const method = findShippingMethod(root, false, 0);
    if (method) return method;
  }
  return "";
}

async function readWorkflowShippingMethod(request) {
  try {
    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/webhooks/easystore") return "";
    return extractWorkflowShippingMethod(await request.clone().json());
  } catch {
    // The production worker remains authoritative for request validation and JSON
    // errors. This best-effort fallback must never change its response behavior.
    return "";
  }
}

function findShippingMethod(value, inShippingContext, depth) {
  if (depth > 6 || value === undefined || value === null) return "";

  if (typeof value !== "object") {
    return inShippingContext ? firstString(value) : "";
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const method = findShippingMethod(item, inShippingContext, depth + 1);
      if (method) return method;
    }
    return "";
  }

  if (inShippingContext) {
    const direct = firstString(...SHIPPING_LABEL_KEYS.map((key) => value[key]));
    if (direct) return direct;

    for (const child of Object.values(value)) {
      if (!child || typeof child !== "object") continue;
      const method = findShippingMethod(child, true, depth + 1);
      if (method) return method;
    }
  }

  for (const [key, child] of Object.entries(value)) {
    if (!SHIPPING_CONTAINER_KEYS.has(String(key).toLowerCase())) continue;
    const method = findShippingMethod(child, true, depth + 1);
    if (method) return method;
  }

  return "";
}

function isWorkflowMode(value) {
  return String(value ?? "").trim().toLowerCase() === "workflow";
}

function firstString(...values) {
  for (const value of values) {
    if (value === undefined || value === null || typeof value === "object") continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

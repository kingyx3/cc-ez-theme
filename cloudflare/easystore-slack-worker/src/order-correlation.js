const CORRELATION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const MAX_ORDER_ID_LENGTH = 128;
const MAX_ORDER_NUMBER_LENGTH = 100;
const MAX_CUSTOMER_LENGTH = 255;
const MAX_CURRENCY_LENGTH = 16;
const MAX_AMOUNT_LENGTH = 100;
const MAX_DELIVERY_LENGTH = 255;
const MAX_URL_LENGTH = 2000;

export const ORDER_CORRELATION_TTL_MS = CORRELATION_TTL_MS;

// Kept as a plain module-worker class so Node's unit-test runner can import the
// production entrypoint without needing the cloudflare:workers runtime module.
// Cloudflare still supplies the DurableObjectState-compatible first argument.
export class OrderCorrelation {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/snapshot") {
      const snapshot = await this.ctx.storage.get("snapshot");
      if (!snapshot) return new Response(null, { status: 404 });
      return Response.json(snapshot, { headers: { "cache-control": "no-store" } });
    }

    if (request.method === "PUT" && url.pathname === "/snapshot") {
      let incoming;
      try {
        incoming = await request.json();
      } catch {
        return Response.json({ ok: false, error: "invalid_json" }, { status: 400 });
      }

      const previous = await this.ctx.storage.get("snapshot");
      const snapshot = mergeSnapshots(previous, incoming);
      if (!snapshot.number) {
        return Response.json({ ok: false, error: "missing_order_number" }, { status: 400 });
      }

      await this.ctx.storage.put("snapshot", snapshot);
      await this.ctx.storage.setAlarm(Date.now() + CORRELATION_TTL_MS);
      return Response.json({ ok: true });
    }

    return new Response("Not found", { status: 404 });
  }

  async alarm() {
    await this.ctx.storage.deleteAll();
  }
}

export async function correlateWorkflowOrder(message, env) {
  if (!message || typeof message !== "object" || Array.isArray(message)) return message;
  if (!message.event || typeof message.event !== "object" || Array.isArray(message.event)) return message;
  if (!env?.ORDER_CORRELATION?.getByName) return message;

  const event = message.event;
  const order = { ...(event.order ?? {}) };
  const resource = { ...(event.resource ?? {}) };
  const topic = normalizeTopic(message.topic ?? event.topic);
  const orderId = limitString(firstString(order.id, resource.type === "order" ? resource.id : ""), MAX_ORDER_ID_LENGTH);
  if (!orderId) return message;

  const shopKey = limitString(firstString(event.shopDomain, message.shopDomain, event.storeLabel, "easystore").toLowerCase(), 255);
  const stub = env.ORDER_CORRELATION.getByName(`${shopKey}:${orderId}`);

  try {
    const humanNumber = normalizeOrderNumber(order.number, orderId);
    let snapshot = null;

    // EasyStore lifecycle events may keep the customer-facing order number while
    // omitting fields selected earlier at checkout, especially shipping method.
    // Hydrate whenever a notification-critical order field is missing.
    if (needsSnapshotHydration(order, humanNumber)) snapshot = await readSnapshot(stub);

    const hydratedOrder = {
      ...order,
      number: firstString(humanNumber, snapshot?.number, order.number),
      customer: firstString(order.customer, snapshot?.customer),
      currency: firstString(order.currency, snapshot?.currency),
      total: firstPresent(order.total, snapshot?.total),
      paid: firstPresent(order.paid, snapshot?.paid),
      shippingMethod: firstString(order.shippingMethod, snapshot?.shippingMethod),
      url: firstString(order.url, snapshot?.url),
    };

    const correlated = {
      ...message,
      topic,
      event: {
        ...event,
        topic,
        order: hydratedOrder,
        resource,
      },
    };

    const normalizedNumber = normalizeOrderNumber(hydratedOrder.number, orderId);
    if (normalizedNumber) {
      correlated.event.order.number = normalizedNumber;
      await writeSnapshot(stub, snapshotFromEvent(correlated.event, orderId));
    }

    return correlated;
  } catch (error) {
    console.warn(JSON.stringify({
      event: "order_correlation_error",
      topic: topic || null,
      orderId,
      message: error instanceof Error ? error.message : String(error),
    }));
    return message;
  }
}

async function readSnapshot(stub) {
  const response = await stub.fetch("https://order-correlation.internal/snapshot");
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Order correlation read failed with ${response.status}`);
  return normalizeSnapshot(await response.json());
}

async function writeSnapshot(stub, snapshot) {
  const response = await stub.fetch("https://order-correlation.internal/snapshot", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(snapshot),
  });
  if (!response.ok) throw new Error(`Order correlation write failed with ${response.status}`);
}

function snapshotFromEvent(event, orderId) {
  const order = event.order ?? {};
  return normalizeSnapshot({
    orderId,
    number: normalizeOrderNumber(order.number, orderId),
    customer: order.customer,
    currency: order.currency,
    total: order.total,
    paid: order.paid,
    shippingMethod: order.shippingMethod,
    url: order.url,
  });
}

function mergeSnapshots(previous, incoming) {
  const before = normalizeSnapshot(previous ?? {});
  const next = normalizeSnapshot(incoming ?? {});
  return normalizeSnapshot({
    orderId: firstString(next.orderId, before.orderId),
    number: firstString(next.number, before.number),
    customer: firstString(next.customer, before.customer),
    currency: firstString(next.currency, before.currency),
    total: firstPresent(next.total, before.total),
    paid: firstPresent(next.paid, before.paid),
    shippingMethod: firstString(next.shippingMethod, before.shippingMethod),
    url: firstString(next.url, before.url),
    updatedAt: new Date().toISOString(),
  });
}

function normalizeSnapshot(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) value = {};
  return {
    orderId: limitString(firstString(value.orderId), MAX_ORDER_ID_LENGTH),
    number: limitString(normalizeOrderNumber(value.number, value.orderId), MAX_ORDER_NUMBER_LENGTH),
    customer: limitString(firstString(value.customer), MAX_CUSTOMER_LENGTH),
    currency: limitString(firstString(value.currency), MAX_CURRENCY_LENGTH),
    total: limitString(firstString(value.total), MAX_AMOUNT_LENGTH),
    paid: limitString(firstString(value.paid), MAX_AMOUNT_LENGTH),
    shippingMethod: limitString(firstString(value.shippingMethod), MAX_DELIVERY_LENGTH),
    url: normalizeHttpsUrl(value.url),
    updatedAt: limitString(firstString(value.updatedAt), 64),
  };
}

function normalizeOrderNumber(number, orderId) {
  const raw = firstString(number);
  if (!raw) return "";
  const plain = raw.replace(/^order\s*/i, "").replace(/^#+\s*/, "").trim();
  if (!plain) return "";
  const normalizedId = firstString(orderId).replace(/^#+\s*/, "").trim();
  if (normalizedId && plain === normalizedId) return "";
  return `#${plain}`;
}

function needsSnapshotHydration(order, humanNumber) {
  return !humanNumber
    || !firstString(order.customer)
    || !firstString(order.currency)
    || firstPresent(order.total) === ""
    || !firstString(order.shippingMethod);
}

function normalizeHttpsUrl(value) {
  const raw = firstString(value);
  if (!raw) return "";
  try {
    const url = new URL(raw);
    return url.protocol === "https:" ? limitString(url.toString(), MAX_URL_LENGTH) : "";
  } catch {
    return "";
  }
}

function normalizeTopic(value) {
  return firstString(value).toLowerCase();
}

function firstPresent(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "";
}

function firstString(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

function limitString(value, maxLength) {
  const text = String(value ?? "");
  return text.length <= maxLength ? text : text.slice(0, maxLength);
}

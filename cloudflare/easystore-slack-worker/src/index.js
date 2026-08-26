const encoder = new TextEncoder();
const decoder = new TextDecoder();

const DEFAULT_MAX_BODY_BYTES = 256 * 1024;
const DEFAULT_SLACK_TIMEOUT_MS = 7000;
const DEFAULT_SLACK_MODE = "incoming_webhook";

export const SUPPORTED_TOPICS = Object.freeze([
  "app/uninstall",
  "store/update",
  "product/create",
  "product/update",
  "product/delete",
  "customer/create",
  "customer/delete",
  "order/create",
  "order/update",
  "order/paid",
  "order/cancel",
  "order/partially_paid",
  "fulfillment/create",
  "fulfillment/update",
  "fulfillment/cancel",
  "refund/create",
  "channel/inventory_update",
]);

const TOPIC_PROFILES = Object.freeze({
  "app/uninstall": { emoji: "🔌", label: "EasyStore app uninstalled", kind: "app" },
  "store/update": { emoji: "🏪", label: "EasyStore store updated", kind: "store" },
  "product/create": { emoji: "🆕", label: "Product created", kind: "product" },
  "product/update": { emoji: "✏️", label: "Product updated", kind: "product" },
  "product/delete": { emoji: "🗑️", label: "Product deleted", kind: "product" },
  "customer/create": { emoji: "👤", label: "Customer created", kind: "customer" },
  "customer/delete": { emoji: "🗑️", label: "Customer deleted", kind: "customer" },
  "order/create": { emoji: "🛍️", label: "New EasyStore order", kind: "order" },
  "order/update": { emoji: "📝", label: "EasyStore order updated", kind: "order" },
  "order/paid": { emoji: "💰", label: "EasyStore order paid", kind: "order" },
  "order/cancel": { emoji: "❌", label: "EasyStore order cancelled", kind: "order" },
  "order/partially_paid": { emoji: "💵", label: "EasyStore order partially paid", kind: "order" },
  "fulfillment/create": { emoji: "📦", label: "Fulfilment created", kind: "fulfillment" },
  "fulfillment/update": { emoji: "🚚", label: "Fulfilment updated", kind: "fulfillment" },
  "fulfillment/cancel": { emoji: "📭", label: "Fulfilment cancelled", kind: "fulfillment" },
  "refund/create": { emoji: "↩️", label: "Refund created", kind: "refund" },
  "channel/inventory_update": { emoji: "📊", label: "Inventory updated", kind: "inventory" },
});

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const requestId = crypto.randomUUID();

    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse({
        ok: true,
        service: "cc-easystore-slack",
        supportedTopics: SUPPORTED_TOPICS.length,
        slackMode: normalizeSlackMode(env.SLACK_MODE),
      }, 200, requestId);
    }

    if (request.method !== "POST" || url.pathname !== "/webhooks/easystore") {
      return jsonResponse({ ok: false, error: "not_found" }, 404, requestId);
    }

    try {
      requireConfig(env);
      const maxBodyBytes = parsePositiveInteger(env.MAX_BODY_BYTES, DEFAULT_MAX_BODY_BYTES);
      const rawBody = await readBodyWithLimit(request, maxBodyBytes);
      const signature = request.headers.get("EasyStore-Hmac-SHA256") ?? request.headers.get("Easystore-Hmac-Sha256");
      const verified = await verifyEasyStoreSignature(rawBody, signature ?? "", env.EASYSTORE_APP_SECRET);

      if (!verified) {
        console.warn(JSON.stringify({ event: "easystore_webhook_rejected", requestId, reason: "invalid_hmac" }));
        return jsonResponse({ ok: false, error: "invalid_hmac" }, 401, requestId);
      }

      let payload;
      try {
        payload = JSON.parse(decoder.decode(rawBody));
      } catch {
        return jsonResponse({ ok: false, error: "invalid_json" }, 400, requestId);
      }

      const topic = normalizeTopic(
        request.headers.get("Easystore-Topic") ??
        request.headers.get("EasyStore-Topic") ??
        firstString(payload?.topic, payload?.event, payload?.type),
      );
      const shopDomain =
        request.headers.get("Easystore-Shop-Domain") ??
        request.headers.get("EasyStore-Shop-Domain") ??
        firstString(payload?.shop_domain, payload?.shop?.domain, payload?.store?.domain);

      if (!isTopicAllowed(topic, env.ALLOWED_TOPICS)) {
        console.log(JSON.stringify({ event: "easystore_webhook_ignored", requestId, topic: topic || null, shopDomain: shopDomain || null }));
        return jsonResponse({ ok: true, ignored: true }, 200, requestId);
      }

      const normalized = normalizeEvent(payload, {
        topic,
        shopDomain,
        storeLabel: env.STORE_LABEL,
        orderUrlTemplate: env.ORDER_URL_TEMPLATE,
        productUrlTemplate: env.PRODUCT_URL_TEMPLATE,
      });
      const slackMode = normalizeSlackMode(env.SLACK_MODE);
      const slackPayload = slackMode === "workflow" ? buildSlackWorkflowPayload(normalized) : buildSlackPayload(normalized);
      const timeoutMs = parsePositiveInteger(env.SLACK_TIMEOUT_MS, DEFAULT_SLACK_TIMEOUT_MS);
      const slackResponse = await postToSlack(env.SLACK_WEBHOOK_URL, slackPayload, timeoutMs);

      if (!slackResponse.ok) {
        console.error(JSON.stringify({
          event: "slack_delivery_failed",
          requestId,
          status: slackResponse.status,
          topic: normalized.topic || null,
          resourceType: normalized.resource.type || null,
          resourceId: normalized.resource.id || null,
        }));
        return jsonResponse({ ok: false, error: "slack_delivery_failed" }, 502, requestId);
      }

      console.log(JSON.stringify({
        event: "easystore_webhook_delivered",
        requestId,
        topic: normalized.topic || null,
        shopDomain: normalized.shopDomain || null,
        resourceType: normalized.resource.type || null,
        resourceId: normalized.resource.id || null,
        slackMode,
      }));
      return jsonResponse({ ok: true }, 200, requestId);
    } catch (error) {
      if (error instanceof BodyTooLargeError) return jsonResponse({ ok: false, error: "payload_too_large" }, 413, requestId);
      const message = error instanceof Error ? error.message : String(error);
      console.error(JSON.stringify({ event: "easystore_webhook_error", requestId, message }));
      return jsonResponse({ ok: false, error: "internal_error" }, 500, requestId);
    }
  },
};

function requireConfig(env) {
  if (!env.SLACK_WEBHOOK_URL) throw new Error("Missing SLACK_WEBHOOK_URL secret");
  if (!env.EASYSTORE_APP_SECRET) throw new Error("Missing EASYSTORE_APP_SECRET secret");
  normalizeSlackMode(env.SLACK_MODE);
}

function normalizeSlackMode(value) {
  const mode = firstString(value, DEFAULT_SLACK_MODE).toLowerCase();
  if (!["incoming_webhook", "workflow"].includes(mode)) throw new Error(`Unsupported SLACK_MODE: ${mode}`);
  return mode;
}

async function readBodyWithLimit(request, maxBytes) {
  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > maxBytes) throw new BodyTooLargeError();
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw new BodyTooLargeError();
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

export async function verifyEasyStoreSignature(rawBody, providedSignature, secret) {
  if (!providedSignature || !secret) return false;
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, rawBody);
  const expectedHex = bytesToHex(new Uint8Array(signature));
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(providedSignature.trim().toLowerCase())),
    crypto.subtle.digest("SHA-256", encoder.encode(expectedHex)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

function bytesToHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function parsePositiveInteger(value, fallback) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeTopic(topic) {
  return firstString(topic).toLowerCase();
}

export function isTopicAllowed(topic, configured) {
  const normalized = normalizeTopic(topic);
  if (!SUPPORTED_TOPICS.includes(normalized)) return false;
  if (!configured?.trim()) return true;
  const allowed = configured.split(",").map(normalizeTopic).filter(Boolean);
  return allowed.includes(normalized);
}

export function normalizeEvent(payload, options = {}) {
  const topic = normalizeTopic(firstString(options.topic, payload?.topic, payload?.event, payload?.type));
  const profile = TOPIC_PROFILES[topic] ?? { emoji: "🔔", label: "EasyStore event", kind: "event" };
  const shopDomain = firstString(options.shopDomain, payload?.shop_domain, payload?.shop?.domain, payload?.store?.domain);
  const storeLabel = firstString(options.storeLabel, payload?.shop?.name, payload?.store?.name, "EasyStore");
  const order = normalizeOrder(payload, { shopDomain, orderUrlTemplate: options.orderUrlTemplate });
  const resource = normalizeResource(profile.kind, payload, order, { shopDomain, productUrlTemplate: options.productUrlTemplate });
  const fields = buildEventFields(profile.kind, payload, order, resource, { shopDomain, storeLabel });
  const heading = buildHeading(profile, order, resource);
  return { topic, kind: profile.kind, heading, shopDomain, storeLabel, resource, order, fields };
}

function normalizeOrder(payload, options = {}) {
  const order = findResource(payload, "order");
  const number = firstString(order?.order_number, order?.order_no, order?.number, order?.name, order?.reference, order?.reference_number, order?.id, payload?.order_number);
  const id = firstString(order?.id, order?.order_id, payload?.order_id);
  const currency = firstString(order?.currency_code, order?.currency, order?.currencyCode, payload?.currency_code);
  const total = firstValue(order?.total_price, order?.total, order?.total_amount, order?.grand_total, order?.amount);
  const paid = firstValue(order?.total_paid_amount, order?.paid_amount, order?.amount_paid);
  const due = firstValue(order?.amount_due, order?.total_unpaid_amount, order?.unpaid_amount);
  const paymentStatus = firstString(order?.financial_status, order?.payment_status, order?.payment?.status);
  const fulfillmentStatus = firstString(order?.fulfillment_status, order?.fulfilment_status, order?.fulfillment?.status);
  const customer = firstString(
    order?.customer?.full_name,
    joinName(order?.customer?.first_name, order?.customer?.last_name),
    order?.customer_name,
    joinName(order?.billing_address?.first_name, order?.billing_address?.last_name),
    joinName(order?.shipping_address?.first_name, order?.shipping_address?.last_name),
  );
  const shippingMethod = firstString(
    order?.shipping_method?.title,
    order?.shipping_method?.name,
    order?.shipping_line?.title,
    order?.shipping_line?.name,
    order?.shipping_lines?.[0]?.title,
    order?.shipping_lines?.[0]?.name,
    order?.delivery_method,
    order?.delivery_name,
  );
  const items = findLineItems(order, payload).map(normalizeLineItem).filter((item) => item.name);
  return {
    id,
    number,
    currency,
    total,
    paid,
    due,
    paymentStatus,
    fulfillmentStatus,
    customer,
    shippingMethod,
    items,
    url: renderUrlTemplate(options.orderUrlTemplate, { id, order_number: number, shop: options.shopDomain }),
  };
}

function normalizeResource(kind, payload, order, options = {}) {
  if (kind === "order") {
    return { type: "order", id: order.id, name: order.number ? `Order #${order.number}` : firstString(order.id), url: order.url, sku: "", inventory: "", status: firstString(order.paymentStatus, order.fulfillmentStatus) };
  }
  if (kind === "product") {
    const product = findResource(payload, "product");
    const id = firstString(product?.id, product?.product_id, payload?.product_id);
    return {
      type: "product",
      id,
      name: firstString(product?.title, product?.name, product?.product_title, product?.handle, id),
      sku: firstString(product?.sku, product?.variants?.[0]?.sku),
      inventory: firstString(product?.inventory_quantity, product?.quantity, product?.variants?.[0]?.inventory_quantity),
      status: firstString(product?.status, product?.published_status),
      price: firstValue(product?.price, product?.price_min, product?.variants?.[0]?.price),
      currency: firstString(product?.currency, payload?.currency),
      url: renderUrlTemplate(options.productUrlTemplate, { id, shop: options.shopDomain }),
    };
  }
  if (kind === "customer") {
    const customer = findResource(payload, "customer");
    return { type: "customer", id: firstString(customer?.id, customer?.customer_id, payload?.customer_id), name: firstString(customer?.full_name, joinName(customer?.first_name, customer?.last_name), customer?.name), url: "", sku: "", inventory: "", status: firstString(customer?.status) };
  }
  if (kind === "fulfillment") {
    const fulfillment = findResource(payload, "fulfillment");
    return {
      type: "fulfillment",
      id: firstString(fulfillment?.id, fulfillment?.fulfillment_id, payload?.fulfillment_id),
      name: firstString(fulfillment?.name, fulfillment?.tracking_number, order.number ? `Order #${order.number}` : ""),
      url: order.url,
      sku: "",
      inventory: "",
      status: firstString(fulfillment?.status, fulfillment?.fulfillment_status),
      trackingCompany: firstString(fulfillment?.tracking_company, fulfillment?.carrier, fulfillment?.shipping_company),
      trackingNumber: firstString(fulfillment?.tracking_number, fulfillment?.tracking_no, fulfillment?.tracking_code),
    };
  }
  if (kind === "refund") {
    const refund = findResource(payload, "refund");
    return {
      type: "refund",
      id: firstString(refund?.id, refund?.refund_id, payload?.refund_id),
      name: order.number ? `Order #${order.number}` : firstString(refund?.name),
      url: order.url,
      sku: "",
      inventory: "",
      status: firstString(refund?.status),
      amount: firstValue(refund?.amount, refund?.refund_amount, refund?.total, payload?.amount),
      currency: firstString(refund?.currency, refund?.currency_code, order.currency, payload?.currency),
      reason: firstString(refund?.reason, refund?.note, refund?.message),
    };
  }
  if (kind === "inventory") {
    const inventory = findInventory(payload);
    return {
      type: "inventory",
      id: firstString(inventory?.variant_id, inventory?.product_id, inventory?.id),
      name: firstString(inventory?.product_title, inventory?.title, inventory?.product?.title, inventory?.name),
      url: "",
      sku: firstString(inventory?.sku, inventory?.variant?.sku),
      inventory: firstString(inventory?.inventory_quantity, inventory?.quantity, inventory?.available, inventory?.available_quantity, inventory?.stock),
      status: "",
      location: firstString(inventory?.location_name, inventory?.location?.name, inventory?.channel_name, inventory?.channel?.name),
    };
  }
  if (kind === "store") {
    const store = findResource(payload, "store");
    return { type: "store", id: firstString(store?.id, store?.store_id, payload?.store_id), name: firstString(store?.name, store?.shop_name, payload?.shop?.name), url: "", sku: "", inventory: "", status: firstString(store?.status) };
  }
  if (kind === "app") {
    const app = findResource(payload, "app");
    return { type: "app", id: firstString(app?.id, app?.app_id, payload?.app_id), name: firstString(app?.name, payload?.app_name, "EasyStore app"), url: "", sku: "", inventory: "", status: "uninstalled" };
  }
  return { type: kind, id: "", name: "", url: "", sku: "", inventory: "", status: "" };
}

function buildEventFields(kind, payload, order, resource, context) {
  const store = firstString(context.shopDomain, context.storeLabel);
  if (kind === "order") return compactFields([
    ["Total", formatMoney(order.total, order.currency)],
    ["Paid", formatMoney(order.paid, order.currency)],
    ["Amount due", formatMoney(order.due, order.currency)],
    ["Payment", humanize(order.paymentStatus)],
    ["Fulfilment", humanize(order.fulfillmentStatus)],
    ["Customer", order.customer],
    ["Delivery", order.shippingMethod],
    ["Store", store],
  ]);
  if (kind === "product") return compactFields([
    ["Product", resource.name], ["Product ID", resource.id], ["SKU", resource.sku], ["Price", formatMoney(resource.price, resource.currency)], ["Inventory", resource.inventory], ["Status", humanize(resource.status)], ["Store", store],
  ]);
  if (kind === "customer") return compactFields([["Customer", resource.name], ["Customer ID", resource.id], ["Store", store]]);
  if (kind === "fulfillment") return compactFields([
    ["Order", order.number ? `#${order.number}` : order.id], ["Fulfilment ID", resource.id], ["Status", humanize(resource.status)], ["Carrier", resource.trackingCompany], ["Tracking", resource.trackingNumber], ["Customer", order.customer], ["Store", store],
  ]);
  if (kind === "refund") return compactFields([
    ["Order", order.number ? `#${order.number}` : order.id], ["Refund ID", resource.id], ["Amount", formatMoney(resource.amount, resource.currency)], ["Reason", resource.reason], ["Status", humanize(resource.status)], ["Store", store],
  ]);
  if (kind === "inventory") return compactFields([
    ["Product", resource.name], ["SKU", resource.sku], ["Quantity", resource.inventory], ["Location / Channel", resource.location], ["Resource ID", resource.id], ["Store", store],
  ]);
  if (kind === "store") {
    const storePayload = findResource(payload, "store");
    return compactFields([["Store", firstString(resource.name, store)], ["Store ID", resource.id], ["Domain", firstString(context.shopDomain, storePayload?.domain, storePayload?.url)], ["Status", humanize(resource.status)]]);
  }
  if (kind === "app") return compactFields([["App", resource.name], ["App ID", resource.id], ["Store", store], ["Status", "Uninstalled"]]);
  return compactFields([["Store", store]]);
}

function compactFields(entries) {
  return entries.filter(([, value]) => value !== undefined && value !== null && value !== "").map(([label, value]) => ({ label, value: String(value) }));
}

function buildHeading(profile, order, resource) {
  const base = `${profile.emoji} ${profile.label}`;
  if (profile.kind === "order" && order.number) return `${base} #${order.number}`;
  if (["fulfillment", "refund"].includes(profile.kind) && order.number) return `${base} — order #${order.number}`;
  if (["product", "customer"].includes(profile.kind) && resource.name) return `${base} — ${resource.name}`;
  if (profile.kind === "inventory" && (resource.sku || resource.name)) return `${base} — ${firstString(resource.sku, resource.name)}`;
  return base;
}

function findResource(payload, key) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return {};
  const candidates = [payload?.[key], payload?.data?.[key], payload?.payload?.[key], payload?.data, payload?.payload, payload];
  return candidates.find((candidate) => candidate && typeof candidate === "object" && !Array.isArray(candidate)) ?? {};
}

function findInventory(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return {};
  return firstObject(payload.inventory, payload.inventory_update, payload.variant, payload.data?.inventory, payload.data?.variant, payload.data, payload);
}

function findLineItems(order, payload) {
  const candidates = [order?.line_items, order?.items, order?.order_items, order?.products, payload?.line_items, payload?.items, payload?.data?.line_items, payload?.fulfillment?.line_items, payload?.data?.fulfillment?.line_items];
  return candidates.find(Array.isArray) ?? [];
}

function normalizeLineItem(item) {
  if (!item || typeof item !== "object") return { name: firstString(item), variant: "", quantity: "" };
  return {
    name: firstString(item.title, item.name, item.product_title, item.product?.title, item.product?.name, item.sku),
    variant: firstString(item.variant_title, item.variant_name, item.variant?.title, item.variant?.name),
    quantity: firstString(item.quantity, item.qty, 1),
  };
}

export function buildSlackPayload(event) {
  const blocks = [{ type: "header", text: { type: "plain_text", text: truncatePlainText(event.heading, 150), emoji: true } }];
  if (event.fields.length > 0) blocks.push({ type: "section", fields: event.fields.slice(0, 10).map(({ label, value }) => slackField(label, value)) });
  if (event.order.items.length > 0 && ["order", "fulfillment"].includes(event.kind)) {
    const itemLines = event.order.items.slice(0, 12).map((item) => {
      const variant = item.variant ? ` — ${escapeMrkdwn(item.variant)}` : "";
      return `• ${escapeMrkdwn(item.name)}${variant} × ${escapeMrkdwn(item.quantity || "1")}`;
    });
    if (event.order.items.length > 12) itemLines.push(`• …and ${event.order.items.length - 12} more`);
    blocks.push({ type: "section", text: { type: "mrkdwn", text: `*Items*\n${itemLines.join("\n")}`.slice(0, 3000) } });
  }
  if (event.resource.url) {
    blocks.push({ type: "actions", elements: [{
      type: "button",
      text: { type: "plain_text", text: event.resource.type === "product" ? "View product" : "View order", emoji: true },
      url: event.resource.url,
      action_id: `view_easystore_${event.resource.type}`.slice(0, 255),
    }] });
  }
  blocks.push({ type: "context", elements: [{ type: "mrkdwn", text: `EasyStore topic: \`${escapeMrkdwn(event.topic)}\`` }] });
  return { text: event.heading, blocks };
}

export function buildSlackWorkflowPayload(event) {
  const fieldSummary = event.fields.map(({ label, value }) => `${label}: ${value}`).join("\n");
  const itemSummary = event.order.items.length > 0
    ? `\nItems:\n${event.order.items.slice(0, 8).map((item) => `• ${item.name}${item.variant ? ` — ${item.variant}` : ""} × ${item.quantity || "1"}`).join("\n")}`
    : "";
  return {
    topic: event.topic || "",
    title: event.heading || "EasyStore event",
    store: firstString(event.shopDomain, event.storeLabel),
    resource: firstString(event.resource.name, event.resource.id, event.resource.type),
    details: `${fieldSummary}${itemSummary}`.trim(),
    order_number: event.order.number || "",
    amount: firstString(formatMoney(event.resource.amount, event.resource.currency), formatMoney(event.order.total, event.order.currency)),
    url: event.resource.url || "",
  };
}

function slackField(label, value) {
  return { type: "mrkdwn", text: `*${escapeMrkdwn(label)}:*\n${escapeMrkdwn(String(value))}`.slice(0, 2000) };
}

function formatMoney(value, currency) {
  if (value === undefined || value === null || value === "") return "";
  const raw = typeof value === "object" ? firstValue(value.amount, value.value, value.total) : value;
  if (raw === undefined || raw === null || raw === "") return "";
  const numeric = Number(raw);
  const rendered = Number.isFinite(numeric)
    ? new Intl.NumberFormat("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric)
    : String(raw);
  return [currency, rendered].filter(Boolean).join(" ");
}

function humanize(value) {
  if (!value) return "";
  return String(value).replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escapeMrkdwn(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function truncatePlainText(value, maxLength) {
  const text = String(value);
  return text.length <= maxLength ? text : `${text.slice(0, maxLength - 1)}…`;
}

export function renderOrderUrl(template, values) {
  return renderUrlTemplate(template, { id: values.id, order_number: values.number, shop: values.shopDomain });
}

export function renderUrlTemplate(template, values) {
  if (!template?.trim()) return "";
  let rendered = template;
  for (const [key, value] of Object.entries(values)) rendered = rendered.replaceAll(`{${key}}`, encodeURIComponent(String(value ?? "")));
  try {
    const url = new URL(rendered);
    return url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

async function postToSlack(webhookUrl, payload, timeoutMs) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort("Slack webhook timeout"), timeoutMs);
  try {
    return await fetch(webhookUrl, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload), signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

function jsonResponse(body, status, requestId) {
  return Response.json(body, { status, headers: { "cache-control": "no-store", "x-request-id": requestId } });
}

function firstString(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

function firstValue(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "");
}

function firstObject(...values) {
  return values.find((value) => value && typeof value === "object" && !Array.isArray(value)) ?? {};
}

function joinName(first, last) {
  return [first, last].filter(Boolean).join(" ").trim();
}

class BodyTooLargeError extends Error {
  constructor() {
    super("Request body exceeds configured limit");
    this.name = "BodyTooLargeError";
  }
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

const DEFAULT_MAX_BODY_BYTES = 256 * 1024;
const DEFAULT_SLACK_TIMEOUT_MS = 7000;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const requestId = crypto.randomUUID();

    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse({ ok: true, service: "cc-easystore-slack" }, 200, requestId);
    }

    if (request.method !== "POST" || url.pathname !== "/webhooks/easystore") {
      return jsonResponse({ ok: false, error: "not_found" }, 404, requestId);
    }

    try {
      requireConfig(env);

      const maxBodyBytes = parsePositiveInteger(env.MAX_BODY_BYTES, DEFAULT_MAX_BODY_BYTES);
      const rawBody = await readBodyWithLimit(request, maxBodyBytes);

      const signature =
        request.headers.get("EasyStore-Hmac-SHA256") ??
        request.headers.get("Easystore-Hmac-Sha256");

      const verified = await verifyEasyStoreSignature(
        rawBody,
        signature ?? "",
        env.EASYSTORE_APP_SECRET,
      );

      if (!verified) {
        console.warn(JSON.stringify({
          event: "easystore_webhook_rejected",
          requestId,
          reason: "invalid_hmac",
        }));
        return jsonResponse({ ok: false, error: "invalid_hmac" }, 401, requestId);
      }

      let payload;
      try {
        payload = JSON.parse(decoder.decode(rawBody));
      } catch {
        return jsonResponse({ ok: false, error: "invalid_json" }, 400, requestId);
      }

      const topic =
        request.headers.get("Easystore-Topic") ??
        request.headers.get("EasyStore-Topic") ??
        firstString(payload?.topic, payload?.event, payload?.type);

      const shopDomain =
        request.headers.get("Easystore-Shop-Domain") ??
        request.headers.get("EasyStore-Shop-Domain") ??
        firstString(payload?.shop_domain, payload?.shop?.domain);

      if (!isTopicAllowed(topic, env.ALLOWED_TOPICS)) {
        console.log(JSON.stringify({
          event: "easystore_webhook_ignored",
          requestId,
          topic: topic || null,
          shopDomain: shopDomain || null,
        }));
        return jsonResponse({ ok: true, ignored: true }, 200, requestId);
      }

      const normalized = normalizeEvent(payload, {
        topic,
        shopDomain,
        storeLabel: env.STORE_LABEL,
        orderUrlTemplate: env.ORDER_URL_TEMPLATE,
      });
      const slackPayload = buildSlackPayload(normalized);

      const timeoutMs = parsePositiveInteger(env.SLACK_TIMEOUT_MS, DEFAULT_SLACK_TIMEOUT_MS);
      const slackResponse = await postToSlack(env.SLACK_WEBHOOK_URL, slackPayload, timeoutMs);

      if (!slackResponse.ok) {
        console.error(JSON.stringify({
          event: "slack_delivery_failed",
          requestId,
          status: slackResponse.status,
          topic: normalized.topic || null,
          orderId: normalized.order.id || null,
          orderNumber: normalized.order.number || null,
        }));
        return jsonResponse({ ok: false, error: "slack_delivery_failed" }, 502, requestId);
      }

      console.log(JSON.stringify({
        event: "easystore_webhook_delivered",
        requestId,
        topic: normalized.topic || null,
        shopDomain: normalized.shopDomain || null,
        orderId: normalized.order.id || null,
        orderNumber: normalized.order.number || null,
      }));

      return jsonResponse({ ok: true }, 200, requestId);
    } catch (error) {
      if (error instanceof BodyTooLargeError) {
        return jsonResponse({ ok: false, error: "payload_too_large" }, 413, requestId);
      }

      const message = error instanceof Error ? error.message : String(error);
      console.error(JSON.stringify({
        event: "easystore_webhook_error",
        requestId,
        message,
      }));
      return jsonResponse({ ok: false, error: "internal_error" }, 500, requestId);
    }
  },
};

function requireConfig(env) {
  if (!env.SLACK_WEBHOOK_URL) {
    throw new Error("Missing SLACK_WEBHOOK_URL secret");
  }
  if (!env.EASYSTORE_APP_SECRET) {
    throw new Error("Missing EASYSTORE_APP_SECRET secret");
  }
}

async function readBodyWithLimit(request, maxBytes) {
  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > maxBytes) {
    throw new BodyTooLargeError();
  }

  if (!request.body) {
    return new Uint8Array();
  }

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

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

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

function isTopicAllowed(topic, configured) {
  if (!configured?.trim()) return true;

  const allowed = configured
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);

  return allowed.includes((topic ?? "").trim().toLowerCase());
}

export function normalizeEvent(payload, options = {}) {
  const order = findOrder(payload);
  const lineItems = findLineItems(order, payload);

  const number = firstString(
    order?.order_number,
    order?.order_no,
    order?.number,
    order?.name,
    order?.reference,
    order?.reference_number,
    order?.id,
  );

  const id = firstString(order?.id, order?.order_id, payload?.order_id);

  const currency = firstString(
    order?.currency_code,
    order?.currency,
    order?.currencyCode,
    payload?.currency_code,
  );

  const total = firstValue(
    order?.total_price,
    order?.total,
    order?.total_amount,
    order?.grand_total,
    order?.amount,
  );

  const paymentStatus = firstString(
    order?.financial_status,
    order?.payment_status,
    order?.payment?.status,
  );

  const fulfillmentStatus = firstString(
    order?.fulfillment_status,
    order?.fulfilment_status,
    order?.fulfillment?.status,
  );

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

  return {
    topic: firstString(options.topic, payload?.topic, payload?.event, payload?.type),
    shopDomain: firstString(options.shopDomain, payload?.shop_domain, payload?.shop?.domain),
    storeLabel: firstString(options.storeLabel, payload?.shop?.name, "EasyStore"),
    order: {
      id,
      number,
      currency,
      total,
      paymentStatus,
      fulfillmentStatus,
      customer,
      shippingMethod,
      items: lineItems.map(normalizeLineItem).filter((item) => item.name),
      url: renderOrderUrl(options.orderUrlTemplate, { id, number, shopDomain: options.shopDomain }),
    },
  };
}

function findOrder(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return {};

  const candidates = [
    payload.order,
    payload.data?.order,
    payload.payload?.order,
    payload.data,
    payload,
  ];

  for (const candidate of candidates) {
    if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
      if (looksLikeOrder(candidate)) return candidate;
    }
  }

  return payload;
}

function looksLikeOrder(value) {
  return [
    "id",
    "order_id",
    "order_number",
    "order_no",
    "total_price",
    "total_amount",
    "line_items",
    "items",
  ].some((key) => key in value);
}

function findLineItems(order, payload) {
  const candidates = [
    order?.line_items,
    order?.items,
    order?.order_items,
    order?.products,
    payload?.line_items,
    payload?.items,
    payload?.data?.line_items,
  ];
  return candidates.find(Array.isArray) ?? [];
}

function normalizeLineItem(item) {
  if (!item || typeof item !== "object") {
    return { name: firstString(item), variant: "", quantity: "" };
  }

  return {
    name: firstString(
      item.title,
      item.name,
      item.product_title,
      item.product?.title,
      item.product?.name,
      item.sku,
    ),
    variant: firstString(
      item.variant_title,
      item.variant_name,
      item.variant?.title,
      item.variant?.name,
    ),
    quantity: firstString(item.quantity, item.qty, 1),
  };
}

export function buildSlackPayload(event) {
  const order = event.order;
  const heading = eventHeading(event.topic, order.number);
  const total = formatMoney(order.total, order.currency);
  const fields = [
    slackField("Total", total),
    slackField("Payment", humanize(order.paymentStatus)),
    slackField("Fulfilment", humanize(order.fulfillmentStatus)),
    slackField("Customer", order.customer),
    slackField("Delivery", order.shippingMethod),
    slackField("Store", firstString(event.shopDomain, event.storeLabel)),
  ].filter(Boolean);

  const blocks = [
    {
      type: "header",
      text: {
        type: "plain_text",
        text: truncatePlainText(heading, 150),
        emoji: true,
      },
    },
  ];

  if (fields.length > 0) {
    blocks.push({ type: "section", fields: fields.slice(0, 10) });
  }

  if (order.items.length > 0) {
    const itemLines = order.items
      .slice(0, 12)
      .map((item) => {
        const variant = item.variant ? ` — ${escapeMrkdwn(item.variant)}` : "";
        return `• ${escapeMrkdwn(item.name)}${variant} × ${escapeMrkdwn(item.quantity || "1")}`;
      });

    if (order.items.length > 12) {
      itemLines.push(`• …and ${order.items.length - 12} more`);
    }

    blocks.push({
      type: "section",
      text: {
        type: "mrkdwn",
        text: `*Items*\n${itemLines.join("\n")}`.slice(0, 3000),
      },
    });
  }

  if (order.url) {
    blocks.push({
      type: "actions",
      elements: [
        {
          type: "button",
          text: { type: "plain_text", text: "View order", emoji: true },
          url: order.url,
          action_id: "view_easystore_order",
        },
      ],
    });
  }

  return {
    text: heading,
    blocks,
  };
}

function eventHeading(topic, orderNumber) {
  const normalized = (topic ?? "").toLowerCase();
  const suffix = orderNumber ? ` #${orderNumber}` : "";

  if (normalized.includes("refund")) return `↩️ EasyStore refund${suffix}`;
  if (normalized.includes("cancel")) return `❌ EasyStore order cancelled${suffix}`;
  if (normalized.includes("paid") || normalized.includes("payment")) return `💰 EasyStore order paid${suffix}`;
  if (normalized.includes("fulfil") || normalized.includes("fulfill")) return `📦 EasyStore fulfilment update${suffix}`;
  if (normalized.includes("create") || normalized.includes("new") || normalized.includes("order")) {
    return `🛍️ New EasyStore order${suffix}`;
  }
  return `🔔 EasyStore event${suffix}`;
}

function slackField(label, value) {
  if (value === undefined || value === null || value === "") return null;
  return {
    type: "mrkdwn",
    text: `*${label}:*\n${escapeMrkdwn(String(value))}`.slice(0, 2000),
  };
}

function formatMoney(value, currency) {
  if (value === undefined || value === null || value === "") return "";

  const raw = typeof value === "object"
    ? firstValue(value.amount, value.value, value.total)
    : value;

  if (raw === undefined || raw === null || raw === "") return "";

  const numeric = Number(raw);
  const rendered = Number.isFinite(numeric)
    ? new Intl.NumberFormat("en-SG", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(numeric)
    : String(raw);

  return [currency, rendered].filter(Boolean).join(" ");
}

function humanize(value) {
  if (!value) return "";
  return String(value)
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escapeMrkdwn(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function truncatePlainText(value, maxLength) {
  const text = String(value);
  return text.length <= maxLength ? text : `${text.slice(0, maxLength - 1)}…`;
}

export function renderOrderUrl(template, values) {
  if (!template?.trim()) return "";

  const replacements = {
    "{id}": values.id ?? "",
    "{order_number}": values.number ?? "",
    "{shop}": values.shopDomain ?? "",
  };

  let rendered = template;
  for (const [placeholder, value] of Object.entries(replacements)) {
    rendered = rendered.replaceAll(placeholder, encodeURIComponent(String(value)));
  }

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
    return await fetch(webhookUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

function jsonResponse(body, status, requestId) {
  return Response.json(body, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-request-id": requestId,
    },
  });
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

function joinName(first, last) {
  return [first, last].filter(Boolean).join(" ").trim();
}

class BodyTooLargeError extends Error {
  constructor() {
    super("Request body exceeds configured limit");
    this.name = "BodyTooLargeError";
  }
}

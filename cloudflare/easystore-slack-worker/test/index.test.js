import assert from "node:assert/strict";
import test from "node:test";
import { createHmac } from "node:crypto";

import {
  SUPPORTED_TOPICS,
  buildSlackPayload,
  buildSlackWorkflowPayload,
  computeEventId,
  deliverToSlack,
  getSlackMinimumIntervalMs,
  isTopicAllowed,
  normalizeEvent,
  renderOrderUrl,
  retryDelaySeconds,
  validateSlackWebhookUrl,
  verifyEasyStoreSignature,
} from "../src/index.js";

const representativePayloads = {
  app: { app: { id: 7, name: "Cardboard Connector" } },
  store: { store: { id: 2, name: "Cardboard", status: "active" } },
  product: { product: { id: 3, title: "Mailer Box", sku: "MB-1", inventory_quantity: 20, price: "4.90", currency: "SGD" } },
  customer: { customer: { id: 4, first_name: "Ada", last_name: "Lovelace" } },
  order: { order: { id: 5, order_number: "1008", currency_code: "SGD", total_price: "149.90", financial_status: "paid", fulfillment_status: "unfulfilled", customer: { first_name: "Ada", last_name: "Lovelace" }, line_items: [{ title: "Classic Tee", variant_title: "Black / M", quantity: 2 }] } },
  fulfillment: { order: { id: 5, order_number: "1008" }, fulfillment: { id: 6, status: "success", tracking_company: "Ninja Van", tracking_number: "NV123" } },
  refund: { order: { id: 5, order_number: "1008", currency_code: "SGD" }, refund: { id: 8, amount: "12.50", reason: "damaged" } },
  inventory: { inventory: { product_id: 3, product_title: "Mailer Box", sku: "MB-1", available_quantity: 17, channel_name: "Online Store" } },
};

function payloadForTopic(topic) {
  if (topic.startsWith("app/")) return representativePayloads.app;
  if (topic.startsWith("store/")) return representativePayloads.store;
  if (topic.startsWith("product/")) return representativePayloads.product;
  if (topic.startsWith("customer/")) return representativePayloads.customer;
  if (topic.startsWith("order/")) return representativePayloads.order;
  if (topic.startsWith("fulfillment/")) return representativePayloads.fulfillment;
  if (topic.startsWith("refund/")) return representativePayloads.refund;
  return representativePayloads.inventory;
}

test("supports exactly the requested 17 EasyStore topics", () => {
  assert.equal(SUPPORTED_TOPICS.length, 17);
  for (const topic of SUPPORTED_TOPICS) assert.equal(isTopicAllowed(topic), true, topic);
  assert.equal(isTopicAllowed("order/unknown"), false);
});

test("all supported topics normalize to useful event-specific Slack messages", () => {
  for (const topic of SUPPORTED_TOPICS) {
    const event = normalizeEvent(payloadForTopic(topic), {
      topic,
      shopDomain: "cardboard.easy.co",
      storeLabel: "Cardboard",
      eventId: "a".repeat(64),
    });
    const message = buildSlackPayload(event);
    assert.equal(event.topic, topic);
    assert.ok(event.kind);
    assert.ok(message.text.length > 0, topic);
    assert.ok(message.blocks.some((block) => block.type === "header"), topic);
    assert.ok(message.blocks.some((block) => block.type === "context"), topic);
  }
});

test("normalizes nested order payload and preserves useful order fields", () => {
  const event = normalizeEvent(representativePayloads.order, { topic: "order/create", shopDomain: "example.easy.co" });
  assert.equal(event.order.id, "5");
  assert.equal(event.order.number, "1008");
  assert.equal(event.order.currency, "SGD");
  assert.equal(event.order.total, "149.90");
  assert.equal(event.order.customer, "Ada Lovelace");
  assert.deepEqual(event.order.items[0], { name: "Classic Tee", variant: "Black / M", quantity: "2" });
});

test("escapes Slack mrkdwn special characters", () => {
  const message = buildSlackPayload(normalizeEvent({ order: { id: 1, items: [{ name: "A < B & C > D", quantity: 1 }] } }, { topic: "order/create" }));
  const itemBlock = message.blocks.find((block) => block.type === "section" && block.text?.text?.startsWith("*Items*"));
  assert.match(itemBlock.text.text, /A &lt; B &amp; C &gt; D/);
});

test("Workflow Builder payload remains flat and includes event correlation in details", () => {
  const payload = buildSlackWorkflowPayload(normalizeEvent(representativePayloads.refund, {
    topic: "refund/create",
    shopDomain: "cardboard.easy.co",
    eventId: "1234567890abcdef".repeat(4),
  }));
  assert.deepEqual(Object.keys(payload).sort(), ["amount", "details", "order_number", "resource", "store", "title", "topic", "url"].sort());
  assert.equal(payload.topic, "refund/create");
  assert.match(payload.details, /Event ID: 1234567890ab/);
  for (const value of Object.values(payload)) assert.equal(typeof value, "string");
});

test("Slack endpoint validation prevents accidental arbitrary egress", () => {
  assert.match(validateSlackWebhookUrl("https://hooks.slack.com/services/T/B/X", "incoming_webhook"), /hooks\.slack\.com/);
  assert.match(validateSlackWebhookUrl("https://hooks.slack.com/triggers/T/X", "workflow"), /hooks\.slack\.com/);
  assert.throws(() => validateSlackWebhookUrl("https://example.com/services/T/B/X", "incoming_webhook"));
  assert.throws(() => validateSlackWebhookUrl("https://hooks.slack.com/triggers/T/X", "incoming_webhook"));
});

test("Slack pacing is conservative for both delivery modes", () => {
  assert.equal(getSlackMinimumIntervalMs("incoming_webhook"), 1100);
  assert.equal(getSlackMinimumIntervalMs("workflow"), 6500);
});

test("Slack delivery honors 429 Retry-After", async () => {
  const result = await deliverToSlack(
    "https://hooks.slack.com/services/T/B/X",
    { text: "hello" },
    "incoming_webhook",
    1000,
    async () => new Response("rate_limited", { status: 429, headers: { "retry-after": "42" } }),
  );
  assert.equal(result.ok, false);
  assert.equal(result.status, 429);
  assert.equal(result.retryAfterSeconds, 42);
});

test("retry backoff increases and caps", () => {
  assert.equal(retryDelaySeconds(1, 500), 30);
  assert.equal(retryDelaySeconds(2, 500), 60);
  assert.equal(retryDelaySeconds(20, 500), 1920);
  assert.equal(retryDelaySeconds(20, 400), 3600);
});

test("verifies both hex and base64 EasyStore HMAC encodings", async () => {
  const subtle = crypto.subtle;
  const original = subtle.timingSafeEqual;
  Object.defineProperty(subtle, "timingSafeEqual", {
    configurable: true,
    value(a, b) {
      const left = new Uint8Array(a);
      const right = new Uint8Array(b);
      if (left.length !== right.length) return false;
      let diff = 0;
      for (let i = 0; i < left.length; i += 1) diff |= left[i] ^ right[i];
      return diff === 0;
    },
  });
  try {
    const raw = new TextEncoder().encode('{"id":1}');
    const secret = "test-secret";
    const hex = createHmac("sha256", secret).update(raw).digest("hex");
    const base64 = createHmac("sha256", secret).update(raw).digest("base64");
    assert.equal(await verifyEasyStoreSignature(raw, hex, secret), true);
    assert.equal(await verifyEasyStoreSignature(raw, base64, secret), true);
    assert.equal(await verifyEasyStoreSignature(raw, "0".repeat(64), secret), false);
  } finally {
    if (original) Object.defineProperty(subtle, "timingSafeEqual", { configurable: true, value: original });
    else delete subtle.timingSafeEqual;
  }
});

test("event IDs are deterministic and change with topic or body", async () => {
  const body = new TextEncoder().encode('{"id":1}');
  const first = await computeEventId(body, "order/create", "cardboard.easy.co");
  const second = await computeEventId(body, "order/create", "cardboard.easy.co");
  const changed = await computeEventId(body, "order/update", "cardboard.easy.co");
  assert.equal(first, second);
  assert.equal(first.length, 64);
  assert.notEqual(first, changed);
});

test("renders only HTTPS order URL templates", () => {
  assert.equal(renderOrderUrl("https://admin.example/orders/{id}?shop={shop}", { id: "123", number: "1008", shopDomain: "example.easy.co" }), "https://admin.example/orders/123?shop=example.easy.co");
  assert.equal(renderOrderUrl("http://admin.example/orders/{id}", { id: "123", number: "1008", shopDomain: "example.easy.co" }), "");
});

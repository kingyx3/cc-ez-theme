import assert from "node:assert/strict";
import test from "node:test";

import {
  SUPPORTED_TOPICS,
  buildSlackPayload,
  buildSlackWorkflowPayload,
  isTopicAllowed,
  normalizeEvent,
  renderOrderUrl,
} from "../src/index.js";

const EXPECTED_TOPICS = [
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
];

test("supports exactly the configured EasyStore event set", () => {
  assert.deepEqual(SUPPORTED_TOPICS, EXPECTED_TOPICS);
  for (const topic of EXPECTED_TOPICS) assert.equal(isTopicAllowed(topic), true);
  assert.equal(isTopicAllowed("order/unknown"), false);
});

test("normalizes order events with line items and payment fields", () => {
  const event = normalizeEvent({
    order: {
      id: 12345,
      order_number: "1008",
      currency_code: "SGD",
      total_price: "149.90",
      total_paid_amount: "50.00",
      amount_due: "99.90",
      financial_status: "partially_paid",
      fulfillment_status: "unfulfilled",
      customer: { first_name: "Ada", last_name: "Lovelace" },
      line_items: [{ title: "Classic Tee", variant_title: "Black / M", quantity: 2 }],
    },
  }, {
    topic: "order/partially_paid",
    shopDomain: "example.easy.co",
  });

  assert.equal(event.order.id, "12345");
  assert.equal(event.order.number, "1008");
  assert.match(event.heading, /partially paid/i);
  assert.ok(event.fields.some((field) => field.label === "Amount due" && field.value.includes("99.90")));
  assert.deepEqual(event.order.items[0], { name: "Classic Tee", variant: "Black / M", quantity: "2" });
});

test("normalizes product, customer, fulfillment, refund, inventory, store and app events", () => {
  const cases = [
    ["product/update", { product: { id: 7, title: "Mailer Box", sku: "MB-1", inventory_quantity: 12 } }, "product", "Mailer Box"],
    ["customer/create", { customer: { id: 8, first_name: "Grace", last_name: "Hopper" } }, "customer", "Grace Hopper"],
    ["fulfillment/update", { order: { id: 9, order_number: "A-9" }, fulfillment: { id: 10, tracking_number: "TRACK123", status: "shipped" } }, "fulfillment", "TRACK123"],
    ["refund/create", { order: { id: 11, order_number: "A-11", currency: "SGD" }, refund: { id: 12, amount: "18.50", reason: "damaged" } }, "refund", "Order #A-11"],
    ["channel/inventory_update", { inventory: { product_id: 13, product_title: "Tape", sku: "TP-1", quantity: 44 } }, "inventory", "Tape"],
    ["store/update", { store: { id: 14, name: "Cardboard", domain: "cardboard.sg" } }, "store", "Cardboard"],
    ["app/uninstall", { app: { id: 15, name: "Notifier" } }, "app", "Notifier"],
  ];

  for (const [topic, payload, type, name] of cases) {
    const event = normalizeEvent(payload, { topic });
    assert.equal(event.resource.type, type);
    assert.equal(event.resource.name, name);
    assert.match(event.heading, /\S/);
  }
});

test("builds Block Kit for direct incoming webhooks", () => {
  const event = normalizeEvent({
    product: { id: 7, title: "A < B & C > D", sku: "SKU-7", inventory_quantity: 2 },
  }, { topic: "product/update", shopDomain: "example.easy.co" });
  const message = buildSlackPayload(event);

  assert.match(message.text, /Product updated/);
  assert.ok(message.blocks.some((block) => block.type === "header"));
  const fields = message.blocks.find((block) => Array.isArray(block.fields))?.fields ?? [];
  assert.ok(fields.some((field) => field.text.includes("A &lt; B &amp; C &gt; D")));
});

test("builds flat variables for Slack Workflow Builder", () => {
  const event = normalizeEvent({
    order: { id: 99, order_number: "ES-99", currency: "MYR", total_amount: 88 },
  }, { topic: "order/paid", shopDomain: "example.easy.co" });
  const message = buildSlackWorkflowPayload(event);

  assert.deepEqual(Object.keys(message), [
    "topic", "title", "store", "resource", "details", "order_number", "amount", "url",
  ]);
  assert.equal(message.topic, "order/paid");
  assert.equal(message.order_number, "ES-99");
  assert.match(message.amount, /MYR 88\.00/);
  assert.ok(Object.values(message).every((value) => typeof value === "string"));
});

test("topic allowlist can narrow the supported set", () => {
  const allowed = "order/create, order/paid";
  assert.equal(isTopicAllowed("order/create", allowed), true);
  assert.equal(isTopicAllowed("order/update", allowed), false);
  assert.equal(isTopicAllowed("something/else", allowed), false);
});

test("renders only HTTPS order URL templates", () => {
  assert.equal(
    renderOrderUrl("https://admin.example/orders/{id}?shop={shop}", {
      id: "123",
      number: "1008",
      shopDomain: "example.easy.co",
    }),
    "https://admin.example/orders/123?shop=example.easy.co",
  );
  assert.equal(
    renderOrderUrl("http://admin.example/orders/{id}", { id: "123", number: "1008", shopDomain: "example.easy.co" }),
    "",
  );
});

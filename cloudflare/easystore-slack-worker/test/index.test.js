import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSlackPayload,
  normalizeEvent,
  renderOrderUrl,
} from "../src/index.js";

test("normalizes a nested EasyStore-like order payload", () => {
  const event = normalizeEvent({
    order: {
      id: 12345,
      order_number: "1008",
      currency_code: "SGD",
      total_price: "149.90",
      financial_status: "paid",
      fulfillment_status: "unfulfilled",
      customer: {
        first_name: "Ada",
        last_name: "Lovelace",
      },
      line_items: [
        { title: "Classic Tee", variant_title: "Black / M", quantity: 2 },
      ],
    },
  }, {
    topic: "order/create",
    shopDomain: "example.easy.co",
    storeLabel: "Cardboard",
  });

  assert.equal(event.order.id, "12345");
  assert.equal(event.order.number, "1008");
  assert.equal(event.order.currency, "SGD");
  assert.equal(event.order.total, "149.90");
  assert.equal(event.order.customer, "Ada Lovelace");
  assert.deepEqual(event.order.items[0], {
    name: "Classic Tee",
    variant: "Black / M",
    quantity: "2",
  });
});

test("accepts root-level order data and builds Slack blocks", () => {
  const event = normalizeEvent({
    id: 99,
    number: "ES-99",
    currency: "MYR",
    total_amount: 88,
    items: [
      { name: "Mailer Box", qty: 3 },
    ],
  }, {
    topic: "order/paid",
  });

  const message = buildSlackPayload(event);

  assert.match(message.text, /order paid/i);
  assert.match(message.text, /ES-99/);
  assert.ok(message.blocks.some((block) => block.type === "header"));
  assert.ok(message.blocks.some((block) => block.type === "section"));
});

test("escapes Slack mrkdwn special characters in item names", () => {
  const message = buildSlackPayload(normalizeEvent({
    id: 1,
    items: [{ name: "A < B & C > D", quantity: 1 }],
  }, { topic: "order/create" }));

  const itemBlock = message.blocks.find(
    (block) => block.type === "section" && block.text?.text?.startsWith("*Items*"),
  );

  assert.match(itemBlock.text.text, /A &lt; B &amp; C &gt; D/);
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
    renderOrderUrl("http://admin.example/orders/{id}", {
      id: "123",
      number: "1008",
      shopDomain: "example.easy.co",
    }),
    "",
  );
});

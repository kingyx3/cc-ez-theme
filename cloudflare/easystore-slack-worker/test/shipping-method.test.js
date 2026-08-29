import assert from "node:assert/strict";
import test from "node:test";

import { buildSlackWorkflowPayload, normalizeEvent } from "../src/index.js";
import { prepareWorkflowQueueMessage } from "../src/production.js";

test("paid-order workflow includes the selected EasyStore shipping method", () => {
  const event = normalizeEvent({
    order: {
      id: "114408999",
      order_number: "1119",
      currency_code: "SGD",
      total_price: "2880.00",
      total_paid_amount: "2880.00",
      financial_status: "paid",
      customer: { first_name: "Ben", last_name: "Ho" },
      shipping_methods: [{ name: "Standard Shipping" }],
      line_items: [{ title: "MTG-FRA-CBB-EN-CASE6", quantity: 1 }],
    },
  }, { topic: "order/paid" });

  assert.equal(event.order.shippingMethod, "Standard Shipping");

  const prepared = prepareWorkflowQueueMessage({
    schemaVersion: 1,
    eventId: "a".repeat(64),
    topic: "order/paid",
    event,
  });
  const slack = buildSlackWorkflowPayload(prepared.event);

  assert.equal(slack.title, "💰 Order #1119 paid · SGD 2,880.00");
  assert.match(slack.details, /Customer: Ben Ho/);
  assert.match(slack.details, /Delivery: Standard Shipping/);
  assert.match(slack.details, /MTG-FRA-CBB-EN-CASE6 × 1/);
});

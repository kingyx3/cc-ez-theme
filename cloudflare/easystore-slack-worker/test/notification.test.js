import assert from "node:assert/strict";
import test from "node:test";

import { buildSlackWorkflowPayload } from "../src/index.js";
import productionWorker, {
  WORKFLOW_NOTIFICATION_TOPICS,
  prepareWorkflowQueueMessage,
  shouldDeliverWorkflowNotification,
} from "../src/production.js";

function orderMessage(overrides = {}) {
  return {
    schemaVersion: 1,
    eventId: "7b0311a2d364".padEnd(64, "0"),
    topic: "order/create",
    event: {
      topic: "order/create",
      kind: "order",
      heading: "🛍️ New EasyStore order ##1113",
      shopDomain: "cardboardcollective.easy.co",
      storeLabel: "Cardboard",
      eventId: "7b0311a2d364".padEnd(64, "0"),
      order: {
        id: "114408393",
        number: "#1113",
        currency: "SGD",
        total: "208.00",
        paid: "",
        due: "208.00",
        paymentStatus: "unpaid",
        fulfillmentStatus: "unfulfilled",
        customer: "J T",
        shippingMethod: "",
        items: [{ name: "MTG-HOB-PBB-EN", variant: "", quantity: "1" }],
        itemCount: 1,
        url: "",
      },
      resource: {
        type: "order",
        id: "114408393",
        name: "Order ##1113",
        url: "",
      },
      fields: [
        { label: "Total", value: "SGD 208.00" },
        { label: "Amount due", value: "SGD 208.00" },
        { label: "Payment", value: "Unpaid" },
        { label: "Fulfilment", value: "Unfulfilled" },
        { label: "Customer", value: "J T" },
        { label: "Store", value: "cardboardcollective.easy.co" },
      ],
      ...overrides,
    },
  };
}

test("workflow delivery keeps only meaningful order lifecycle topics", () => {
  assert.deepEqual(WORKFLOW_NOTIFICATION_TOPICS, [
    "order/create",
    "order/paid",
    "order/partially_paid",
    "order/cancel",
    "fulfillment/create",
    "fulfillment/cancel",
    "refund/create",
  ]);

  for (const topic of WORKFLOW_NOTIFICATION_TOPICS) {
    assert.equal(shouldDeliverWorkflowNotification(topic), true, topic);
  }

  for (const topic of [
    "product/update",
    "channel/inventory_update",
    "order/update",
    "fulfillment/update",
    "product/create",
    "customer/create",
    "store/update",
  ]) {
    assert.equal(shouldDeliverWorkflowNotification(topic), false, topic);
  }
});

test("new-order workflow message is concise and never doubles the order hash", () => {
  const prepared = prepareWorkflowQueueMessage(orderMessage());

  assert.equal(prepared.event.order.number, "#1113");
  assert.equal(prepared.event.resource.name, "Order #1113");
  assert.equal(prepared.event.heading, "🛍️ New order #1113 · SGD 208.00 · Unpaid");
  assert.deepEqual(prepared.event.fields, [{ label: "Customer", value: "J T" }]);
  assert.equal(prepared.event.eventId, "");

  const slack = buildSlackWorkflowPayload(prepared.event);
  assert.equal(slack.title, "🛍️ New order #1113 · SGD 208.00 · Unpaid");
  assert.equal(slack.order_number, "#1113");
  assert.equal(slack.resource, "Order #1113");
  assert.equal(slack.amount, "SGD 208.00");
  assert.match(slack.details, /Customer: J T/);
  assert.match(slack.details, /MTG-HOB-PBB-EN × 1/);
  assert.doesNotMatch(slack.details, /Event ID:/);
  assert.doesNotMatch(slack.details, /Store:/);
  assert.doesNotMatch(slack.details, /Amount due:/);
});

test("cancellation without a human order number clearly uses the EasyStore ID", () => {
  const message = orderMessage({
    topic: "order/cancel",
    heading: "❌ EasyStore order cancelled",
    order: {
      id: "114408393",
      number: "114408393",
      currency: "",
      total: "",
      customer: "",
      shippingMethod: "",
      items: [],
      itemCount: 0,
      url: "",
    },
    resource: {
      type: "order",
      id: "114408393",
      name: "114408393",
      url: "",
    },
    fields: [{ label: "Store", value: "cardboardcollective.easy.co" }],
  });
  message.topic = "order/cancel";

  const prepared = prepareWorkflowQueueMessage(message);
  const slack = buildSlackWorkflowPayload(prepared.event);

  assert.equal(prepared.event.order.number, "");
  assert.equal(prepared.event.resource.name, "EasyStore order 114408393");
  assert.equal(prepared.event.heading, "❌ Order cancelled · EasyStore ID 114408393");
  assert.deepEqual(prepared.event.fields, [{ label: "EasyStore order ID", value: "114408393" }]);
  assert.equal(slack.order_number, "");
  assert.equal(slack.resource, "EasyStore order 114408393");
  assert.doesNotMatch(slack.details, /Event ID:/);
});

test("workflow queue acknowledges noisy side-effect events without calling Slack", async () => {
  let acknowledgements = 0;
  const message = {
    id: "queue-1",
    attempts: 1,
    body: {
      schemaVersion: 1,
      eventId: "abc123",
      topic: "product/update",
      event: { topic: "product/update" },
    },
    ack() { acknowledgements += 1; },
    retry() { throw new Error("suppressed notifications must not retry"); },
  };

  const result = await productionWorker.queue({ messages: [message] }, { SLACK_MODE: "workflow" }, {});
  assert.equal(result, undefined);
  assert.equal(acknowledgements, 1);
});

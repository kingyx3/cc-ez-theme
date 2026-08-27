import assert from "node:assert/strict";
import test from "node:test";

import { buildSlackWorkflowPayload } from "../src/index.js";
import { prepareWorkflowQueueMessage } from "../src/production.js";
import {
  ORDER_CORRELATION_TTL_MS,
  OrderCorrelation,
  correlateWorkflowOrder,
} from "../src/order-correlation.js";

class MemoryStorage {
  constructor() {
    this.values = new Map();
    this.alarm = null;
  }

  async get(key) {
    return this.values.get(key);
  }

  async put(key, value) {
    this.values.set(key, structuredClone(value));
  }

  async setAlarm(timestamp) {
    this.alarm = timestamp;
  }

  async deleteAll() {
    this.values.clear();
    this.alarm = null;
  }
}

class MemoryCorrelationNamespace {
  constructor() {
    this.objects = new Map();
  }

  getByName(name) {
    if (!this.objects.has(name)) {
      const storage = new MemoryStorage();
      this.objects.set(name, {
        storage,
        object: new OrderCorrelation({ storage }, {}),
      });
    }

    const record = this.objects.get(name);
    return {
      fetch(input, init) {
        const request = input instanceof Request ? input : new Request(input, init);
        return record.object.fetch(request);
      },
    };
  }
}

function richOrderCreate() {
  return {
    schemaVersion: 1,
    eventId: "create-1114".padEnd(64, "0"),
    topic: "order/create",
    shopDomain: "cardboardcollective.easy.co",
    event: {
      topic: "order/create",
      kind: "order",
      shopDomain: "cardboardcollective.easy.co",
      storeLabel: "Cardboard",
      heading: "🛍️ New order #1114 · SGD 168.00 · Unpaid",
      eventId: "",
      order: {
        id: "114410861",
        number: "#1114",
        currency: "SGD",
        total: "168.00",
        paid: "",
        due: "168.00",
        paymentStatus: "unpaid",
        fulfillmentStatus: "unfulfilled",
        customer: "Bry Test 2",
        shippingMethod: "",
        items: [{ name: "MTG-FRA-SLB-EN", variant: "", quantity: "1" }],
        itemCount: 1,
        url: "",
      },
      resource: {
        type: "order",
        id: "114410861",
        name: "Order #1114",
        url: "",
      },
      fields: [{ label: "Customer", value: "Bry Test 2" }],
    },
  };
}

function sparseOrderCancel() {
  return {
    schemaVersion: 1,
    eventId: "cancel-1114".padEnd(64, "0"),
    topic: "order/cancel",
    shopDomain: "cardboardcollective.easy.co",
    event: {
      topic: "order/cancel",
      kind: "order",
      shopDomain: "cardboardcollective.easy.co",
      storeLabel: "Cardboard",
      heading: "❌ Order cancelled · EasyStore ID 114410861",
      eventId: "",
      order: {
        id: "114410861",
        number: "114410861",
        currency: "",
        total: "",
        paid: "",
        due: "",
        paymentStatus: "",
        fulfillmentStatus: "",
        customer: "",
        shippingMethod: "",
        items: [],
        itemCount: 0,
        url: "",
      },
      resource: {
        type: "order",
        id: "114410861",
        name: "EasyStore order 114410861",
        url: "",
      },
      fields: [{ label: "EasyStore order ID", value: "114410861" }],
    },
  };
}

test("sparse cancellation is hydrated from the earlier human order snapshot", async () => {
  const namespace = new MemoryCorrelationNamespace();
  const env = { ORDER_CORRELATION: namespace };

  await correlateWorkflowOrder(richOrderCreate(), env);
  const correlated = await correlateWorkflowOrder(sparseOrderCancel(), env);
  const prepared = prepareWorkflowQueueMessage(correlated);
  const slack = buildSlackWorkflowPayload(prepared.event);

  assert.equal(prepared.event.order.id, "114410861");
  assert.equal(prepared.event.order.number, "#1114");
  assert.equal(prepared.event.order.customer, "Bry Test 2");
  assert.equal(prepared.event.order.currency, "SGD");
  assert.equal(prepared.event.order.total, "168.00");
  assert.equal(prepared.event.heading, "❌ Order #1114 cancelled · SGD 168.00");
  assert.deepEqual(prepared.event.fields, [{ label: "Customer", value: "Bry Test 2" }]);

  assert.equal(slack.title, "❌ Order #1114 cancelled · SGD 168.00");
  assert.equal(slack.order_number, "#1114");
  assert.equal(slack.amount, "SGD 168.00");
  assert.equal(slack.details, "Customer: Bry Test 2");
  assert.doesNotMatch(slack.details, /114410861/);
});

test("order correlation snapshots expire after roughly 30 days", async () => {
  const namespace = new MemoryCorrelationNamespace();
  const env = { ORDER_CORRELATION: namespace };
  const before = Date.now();

  await correlateWorkflowOrder(richOrderCreate(), env);

  const record = namespace.objects.get("cardboardcollective.easy.co:114410861");
  assert.ok(record);
  assert.ok(record.storage.alarm >= before + ORDER_CORRELATION_TTL_MS);
  assert.ok(record.storage.alarm <= Date.now() + ORDER_CORRELATION_TTL_MS);

  await record.object.alarm();
  assert.equal(await record.storage.get("snapshot"), undefined);
});

test("correlation remains optional and degrades to the existing fallback", async () => {
  const original = sparseOrderCancel();
  const correlated = await correlateWorkflowOrder(original, {});
  const prepared = prepareWorkflowQueueMessage(correlated);

  assert.equal(prepared.event.heading, "❌ Order cancelled · EasyStore ID 114410861");
  assert.deepEqual(prepared.event.fields, [{ label: "EasyStore order ID", value: "114410861" }]);
});

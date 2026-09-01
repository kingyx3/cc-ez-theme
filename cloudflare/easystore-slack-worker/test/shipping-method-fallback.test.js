import assert from "node:assert/strict";
import test from "node:test";

import { buildSlackWorkflowPayload } from "../src/index.js";
import {
  applyWorkflowShippingMethod,
  extractWorkflowShippingMethod,
} from "../src/correlated-production.js";
import { prepareWorkflowQueueMessage } from "../src/production.js";

function order1134Message() {
  return {
    schemaVersion: 1,
    eventId: "order-paid-1134".padEnd(64, "0"),
    topic: "order/paid",
    shopDomain: "cardboardcollective.easy.co",
    event: {
      topic: "order/paid",
      kind: "order",
      heading: "EasyStore payment event",
      shopDomain: "cardboardcollective.easy.co",
      storeLabel: "Cardboard",
      resource: {
        type: "order",
        id: "1134-internal-id",
        name: "Order #1134",
        url: "",
      },
      order: {
        id: "1134-internal-id",
        number: "1134",
        currency: "SGD",
        total: "256.00",
        paid: "256.00",
        paymentStatus: "paid",
        customer: "Asyraf Rasid",
        shippingMethod: "",
        items: [
          { name: "MTG-FRA-CMD-EN", variant: "", quantity: "1" },
          { name: "MTG-FRA-SLB-EN", variant: "", quantity: "1" },
        ],
        itemCount: 2,
        url: "",
      },
      fields: [],
      eventId: "",
    },
  };
}

test("extracts scalar EasyStore shipping method variants missed by the normalizer", () => {
  assert.equal(
    extractWorkflowShippingMethod({ order: { shipping_method_name: "Ninja Van Standard" } }),
    "Ninja Van Standard",
  );
  assert.equal(
    extractWorkflowShippingMethod({ data: { order: { shipping_title: "Store Pickup" } } }),
    "Store Pickup",
  );
});

test("Order #1134-style paid notification recovers nested shipping provider", () => {
  const rawPayload = {
    order: {
      shipment: {
        provider: "Ninja Van Standard",
      },
    },
  };

  const shippingMethod = extractWorkflowShippingMethod(rawPayload);
  const enriched = applyWorkflowShippingMethod(order1134Message(), shippingMethod);
  const prepared = prepareWorkflowQueueMessage(enriched);
  const slack = buildSlackWorkflowPayload(prepared.event);

  assert.equal(prepared.event.order.shippingMethod, "Ninja Van Standard");
  assert.equal(slack.title, "💰 Order #1134 paid · SGD 256.00");
  assert.match(slack.details, /Customer: Asyraf Rasid/);
  assert.match(slack.details, /Delivery: Ninja Van Standard/);
  assert.match(slack.details, /MTG-FRA-CMD-EN × 1/);
  assert.match(slack.details, /MTG-FRA-SLB-EN × 1/);
});

test("raw fallback never overwrites an already normalized shipping method", () => {
  const message = order1134Message();
  message.event.order.shippingMethod = "Store Pickup";

  const enriched = applyWorkflowShippingMethod(message, "Ninja Van Standard");
  assert.equal(enriched, message);
  assert.equal(enriched.event.order.shippingMethod, "Store Pickup");
});

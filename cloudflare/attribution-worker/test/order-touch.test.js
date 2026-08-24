import assert from "node:assert/strict";
import test from "node:test";

import worker, { safeDestinationPath } from "../src/index.js";

function fakeDatabase() {
  const writes = [];
  return {
    writes,
    prepare(sql) {
      return {
        bind(...values) {
          return {
            async run() {
              writes.push({ sql, values });
              return { success: true, meta: { changes: 1 } };
            },
          };
        },
      };
    },
  };
}

function context() {
  const pending = [];
  return { pending, waitUntil: (promise) => pending.push(promise) };
}

async function tracked(path, db = fakeDatabase()) {
  const ctx = context();
  const request = new Request(new URL(path, "https://go.cardboard.sg"), {
    headers: { "user-agent": "Mozilla/5.0 Safari/605.1.15" },
  });
  const response = await worker.fetch(
    request,
    {
      STORE_URL: "https://cardboard.sg/",
      DEFAULT_CAMPAIGN: "always-on",
      DB: db,
    },
    ctx,
  );
  await Promise.all(ctx.pending);
  return { response, db };
}

test("generic campaign URLs carry campaign, content and a safe store destination", async () => {
  const { response, db } = await tracked(
    "/fb?campaign=rf&content=grp-aug26&to=%2Fcollections%2Freality-fracture",
  );

  assert.equal(response.status, 302);
  const location = new URL(response.headers.get("location"));
  assert.equal(location.pathname, "/collections/reality-fracture");
  assert.equal(location.searchParams.get("utm_source"), "facebook");
  assert.equal(location.searchParams.get("utm_medium"), "social");
  assert.equal(location.searchParams.get("utm_campaign"), "rf");
  assert.equal(location.searchParams.get("utm_content"), "grp-aug26");

  assert.equal(db.writes.length, 1);
  assert.equal(db.writes[0].values[3], "rf");
  assert.equal(db.writes[0].values[9], "grp-aug26");
});

test("existing /go links remain valid on the custom domain", async () => {
  const { response } = await tracked("/go/wa?campaign=restock&content=vip");
  const location = new URL(response.headers.get("location"));
  assert.equal(location.searchParams.get("utm_source"), "whatsapp");
  assert.equal(location.searchParams.get("utm_campaign"), "restock");
  assert.equal(location.searchParams.get("utm_content"), "vip");
});

test("legacy RF vanity paths are no longer reserved", async () => {
  assert.equal((await tracked("/rf")).response.status, 404);
  assert.equal((await tracked("/rf-bump")).response.status, 404);
});

test("destination input cannot become an open redirect", () => {
  assert.equal(safeDestinationPath("https://evil.example/x"), "/");
  assert.equal(safeDestinationPath("//evil.example/x"), "/");
  assert.equal(safeDestinationPath("/products/example"), "/products/example");
});

test("a logged-in storefront can bind a real click id to an EasyStore customer", async () => {
  const db = fakeDatabase();
  const clickId = "123e4567-e89b-12d3-a456-426614174000";
  const request = new Request("https://go.cardboard.sg/touch", {
    method: "POST",
    headers: {
      origin: "https://cardboard.sg",
      "content-type": "application/json",
    },
    body: JSON.stringify({ customer_id: "12345", click_id: clickId }),
  });

  const response = await worker.fetch(
    request,
    { STORE_URL: "https://cardboard.sg/", DB: db },
    context(),
  );

  assert.equal(response.status, 200);
  assert.equal((await response.json()).ok, true);
  assert.equal(db.writes.length, 1);
  assert.match(db.writes[0].sql, /INSERT INTO customer_touches/);
  assert.deepEqual(db.writes[0].values.slice(0, 1), ["12345"]);
  assert.equal(db.writes[0].values[2], clickId);
  assert.match(db.writes[0].sql, /COALESCE\(bot, 0\) = 0/);
});

test("touch binding refuses foreign origins and malformed identifiers", async () => {
  const db = fakeDatabase();
  const foreign = new Request("https://go.cardboard.sg/touch", {
    method: "POST",
    headers: { origin: "https://evil.example", "content-type": "application/json" },
    body: JSON.stringify({
      customer_id: "12345",
      click_id: "123e4567-e89b-12d3-a456-426614174000",
    }),
  });
  assert.equal(
    (await worker.fetch(foreign, { STORE_URL: "https://cardboard.sg/", DB: db }, context())).status,
    403,
  );

  const malformed = new Request("https://go.cardboard.sg/touch", {
    method: "POST",
    headers: { origin: "https://cardboard.sg", "content-type": "application/json" },
    body: JSON.stringify({ customer_id: "abc", click_id: "not-a-click" }),
  });
  assert.equal(
    (await worker.fetch(malformed, { STORE_URL: "https://cardboard.sg/", DB: db }, context())).status,
    400,
  );
  assert.equal(db.writes.length, 0);
});

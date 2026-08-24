import assert from "node:assert/strict";
import test from "node:test";

import { ensureWorkerPublic } from "../scripts/ensure-public-access.js";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("creates a worker-level bypass application when none exists", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if ((options.method || "GET") === "GET") {
      return jsonResponse({ success: true, result: [], result_info: { total_pages: 1 } });
    }
    const body = JSON.parse(options.body);
    assert.equal(body.type, "self_hosted");
    assert.deepEqual(body.destinations, [{ type: "worker", worker_id: "cc-attribution" }]);
    assert.equal("destination" in body, false);
    assert.equal(body.policies[0].decision, "bypass");
    assert.deepEqual(body.policies[0].include, [{ everyone: {} }]);
    return jsonResponse({ success: true, result: { id: "app-new" } });
  };

  const result = await ensureWorkerPublic({
    accountId: "acct",
    token: "token",
    fetchImpl,
  });

  assert.equal(result.changed, true);
  assert.equal(result.action, "created_worker_bypass_application");
  assert.equal(calls.length, 2);
});

test("does nothing when a bypass-everyone policy already exists", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/apps?") || url.includes("/apps&page")) {
      return jsonResponse({
        success: true,
        result: [
          {
            id: "app-1",
            destinations: [{ type: "worker", worker_id: "cc-attribution" }],
          },
        ],
        result_info: { total_pages: 1 },
      });
    }
    return jsonResponse({
      success: true,
      result: [{ decision: "bypass", include: [{ everyone: {} }] }],
      result_info: { total_pages: 1 },
    });
  };

  const result = await ensureWorkerPublic({
    accountId: "acct",
    token: "token",
    fetchImpl,
  });

  assert.equal(result.changed, false);
  assert.equal(result.action, "worker_bypass_already_present");
  assert.equal(calls.length, 2);
});

test("adds a bypass policy to an existing worker Access application", async () => {
  const writes = [];
  const fetchImpl = async (url, options = {}) => {
    const method = options.method || "GET";
    if (method === "POST") {
      writes.push(JSON.parse(options.body));
      return jsonResponse({ success: true, result: { id: "policy-new" } });
    }
    if (url.includes("/apps?") || url.includes("/apps&page")) {
      return jsonResponse({
        success: true,
        result: [
          {
            id: "app-1",
            destination: { type: "worker", worker_id: "cc-attribution" },
          },
        ],
        result_info: { total_pages: 1 },
      });
    }
    return jsonResponse({
      success: true,
      result: [{ decision: "allow", include: [{ email_domain: { domain: "example.com" } }] }],
      result_info: { total_pages: 1 },
    });
  };

  const result = await ensureWorkerPublic({
    accountId: "acct",
    token: "token",
    fetchImpl,
  });

  assert.equal(result.changed, true);
  assert.equal(result.action, "created_worker_bypass_policy");
  assert.equal(writes.length, 1);
  assert.equal(writes[0].decision, "bypass");
  assert.deepEqual(writes[0].include, [{ everyone: {} }]);
});

test("surfaces Cloudflare API failures with an Access permission hint", async () => {
  const fetchImpl = async () => jsonResponse({ code: 1010, error: "auth.forbidden" }, 403);

  await assert.rejects(
    ensureWorkerPublic({ accountId: "acct", token: "token", fetchImpl }),
    /auth\.forbidden.*Access: Apps and Policies.*Edit/,
  );
});

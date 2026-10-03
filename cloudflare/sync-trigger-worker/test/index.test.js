import assert from "node:assert/strict";
import test from "node:test";

import { parseEnvironments, runScheduled } from "../src/index.js";

const env = {
  GITHUB_REPOSITORY: "owner/repo",
  WORKFLOW_FILE: "sync.yml",
  WORKFLOW_REF: "main",
  DEPLOYMENT_ENVS: "prod,dev",
  SYNC_TRIGGER_GITHUB_TOKEN: "ghp_test",
};

test("dispatches the workflow once per environment with the token", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return new Response(null, { status: 204 });
  };
  assert.deepEqual(await runScheduled(env, fetchImpl), ["prod", "dev"]);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, "https://api.github.com/repos/owner/repo/actions/workflows/sync.yml/dispatches");
  assert.equal(calls[0].init.headers.Authorization, "Bearer ghp_test");
  assert.deepEqual(JSON.parse(calls[1].init.body), { ref: "main", inputs: { deployment_env: "dev" } });
});

test("one failed dispatch does not stop the other, and the run fails", async () => {
  const seen = [];
  const fetchImpl = async (_url, init) => {
    const name = JSON.parse(init.body).inputs.deployment_env;
    seen.push(name);
    return name === "prod" ? new Response("nope", { status: 403 }) : new Response(null, { status: 204 });
  };
  await assert.rejects(runScheduled(env, fetchImpl), /1 of 2/);
  assert.deepEqual(seen, ["prod", "dev"]);
});

test("missing token fails before any request", async () => {
  await assert.rejects(runScheduled({ ...env, SYNC_TRIGGER_GITHUB_TOKEN: "" }, async () => assert.fail()), /SYNC_TRIGGER_GITHUB_TOKEN/);
});

test("rejects unknown environments", () => {
  assert.throws(() => parseEnvironments("staging"), /Unsupported/);
});

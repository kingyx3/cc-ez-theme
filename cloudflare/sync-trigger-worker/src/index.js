// Cron connector: dispatches the EasyStore -> HubSpot CRM sync workflow on
// GitHub Actions. GitHub's own `schedule` trigger is best-effort and routinely
// starts late; Cloudflare cron fires on time and this Worker only has to ask.
//
// Auth: SYNC_TRIGGER_GITHUB_TOKEN is a Worker secret, provisioned from the
// repository secret of the same name by the deploy workflow. It needs
// "Actions: read and write" on the repository (fine-grained PAT).

const API_VERSION = "2022-11-28";

export function parseEnvironments(value) {
  const envs = String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  for (const env of envs) {
    if (env !== "prod" && env !== "dev") throw new Error(`Unsupported deployment environment: ${env}`);
  }
  if (envs.length === 0) throw new Error("DEPLOYMENT_ENVS must name at least one environment");
  return [...new Set(envs)];
}

export async function dispatchSync(env, deploymentEnv, fetchImpl = fetch) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;
  const response = await fetchImpl(url, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.SYNC_TRIGGER_GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "cc-sync-trigger",
      "X-GitHub-Api-Version": API_VERSION,
    },
    body: JSON.stringify({
      ref: env.WORKFLOW_REF || "main",
      inputs: { deployment_env: deploymentEnv },
    }),
  });
  if (response.status !== 204) {
    const detail = (await response.text().catch(() => "")).slice(0, 500);
    throw new Error(`GitHub dispatch for ${deploymentEnv} failed with HTTP ${response.status}: ${detail}`);
  }
  return deploymentEnv;
}

export async function runScheduled(env, fetchImpl = fetch) {
  if (!env.SYNC_TRIGGER_GITHUB_TOKEN) throw new Error("SYNC_TRIGGER_GITHUB_TOKEN secret is not configured");
  const results = await Promise.allSettled(
    parseEnvironments(env.DEPLOYMENT_ENVS).map((name) => dispatchSync(env, name, fetchImpl)),
  );
  const failures = results.filter((result) => result.status === "rejected");
  for (const failure of failures) console.error(failure.reason.message);
  if (failures.length > 0) {
    throw new Error(`${failures.length} of ${results.length} sync dispatches failed`);
  }
  return results.map((result) => result.value);
}

export default {
  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(runScheduled(env));
  },
  async fetch() {
    return Response.json({ ok: true, worker: "cc-sync-trigger" });
  },
};

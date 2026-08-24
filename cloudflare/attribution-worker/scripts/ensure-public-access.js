const API_BASE = "https://api.cloudflare.com/client/v4";

function authHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function apiRequest(fetchImpl, token, url, options = {}) {
  const response = await fetchImpl(url, {
    ...options,
    headers: {
      ...authHeaders(token),
      ...(options.headers || {}),
    },
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok || payload?.success === false) {
    const errors = Array.isArray(payload?.errors)
      ? payload.errors.map((item) => item?.message || JSON.stringify(item)).join("; ")
      : "";
    const directError = payload?.error ? String(payload.error) : "";
    const code = payload?.code ? `code ${payload.code}` : "";
    const details = [errors, directError, code].filter(Boolean).join("; ");
    const permissionHint = response.status === 403
      ? " Cloudflare token needs Account > Access: Apps and Policies > Edit."
      : "";
    throw new Error(
      `Cloudflare API ${options.method || "GET"} ${url} failed (${response.status})${
        details ? `: ${details}` : ""
      }.${permissionHint}`,
    );
  }

  return payload || { success: true, result: null };
}

async function listPaginated(fetchImpl, token, url) {
  const results = [];
  let page = 1;
  let totalPages = 1;

  do {
    const separator = url.includes("?") ? "&" : "?";
    const payload = await apiRequest(fetchImpl, token, `${url}${separator}page=${page}&per_page=100`);
    if (Array.isArray(payload.result)) results.push(...payload.result);
    totalPages = Number(payload.result_info?.total_pages || 1);
    page += 1;
  } while (page <= totalPages);

  return results;
}

function workerDestination(app) {
  if (app?.destination?.type === "worker") return app.destination;
  if (Array.isArray(app?.destinations)) {
    return app.destinations.find((item) => item?.type === "worker") || null;
  }
  return null;
}

function includesEveryone(policy) {
  return Array.isArray(policy?.include) && policy.include.some((rule) => rule && "everyone" in rule);
}

function isPublicBypass(policy) {
  return policy?.decision === "bypass" && includesEveryone(policy);
}

export async function ensureWorkerPublic({
  accountId,
  token,
  workerId = "cc-attribution",
  fetchImpl = fetch,
}) {
  if (!accountId) throw new Error("CLOUDFLARE_ACCOUNT_ID is required");
  if (!token) throw new Error("A Cloudflare Access API token is required");
  if (!workerId) throw new Error("workerId is required");

  const accountBase = `${API_BASE}/accounts/${accountId}/access`;
  const applications = await listPaginated(fetchImpl, token, `${accountBase}/apps`);
  const application = applications.find(
    (app) => workerDestination(app)?.worker_id === workerId,
  );

  if (!application) {
    const body = {
      name: `${workerId} - public`,
      type: "self_hosted",
      destinations: [{ type: "worker", worker_id: workerId }],
      policies: [
        {
          name: `Public ${workerId}`,
          decision: "bypass",
          include: [{ everyone: {} }],
        },
      ],
    };

    const payload = await apiRequest(fetchImpl, token, `${accountBase}/apps`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    return {
      changed: true,
      action: "created_worker_bypass_application",
      application_id: payload.result?.id || null,
      worker_id: workerId,
    };
  }

  const policies = await listPaginated(
    fetchImpl,
    token,
    `${accountBase}/apps/${application.id}/policies`,
  );

  if (policies.some(isPublicBypass)) {
    return {
      changed: false,
      action: "worker_bypass_already_present",
      application_id: application.id,
      worker_id: workerId,
    };
  }

  await apiRequest(fetchImpl, token, `${accountBase}/apps/${application.id}/policies`, {
    method: "POST",
    body: JSON.stringify({
      name: `Public ${workerId}`,
      decision: "bypass",
      include: [{ everyone: {} }],
    }),
  });

  return {
    changed: true,
    action: "created_worker_bypass_policy",
    application_id: application.id,
    worker_id: workerId,
  };
}

async function main() {
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID || "";
  const token =
    process.env.CLOUDFLARE_ACCESS_API_TOKEN || process.env.CLOUDFLARE_API_TOKEN || "";
  const workerId = process.env.CLOUDFLARE_WORKER_ID || "cc-attribution";
  const result = await ensureWorkerPublic({ accountId, token, workerId });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}

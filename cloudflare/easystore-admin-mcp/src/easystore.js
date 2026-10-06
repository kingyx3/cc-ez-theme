import { ToolError, resolveOperation } from './registry.js';

export const STORE = 'cardboardcollective.easy.co';
const MAX_RESPONSE = 2 * 1024 * 1024;
export async function readLimited(response, limit) {
  const reader = response.body?.getReader();
  if (!reader) return '';
  let size = 0;
  const chunks = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) { await reader.cancel(); throw new ToolError('PAYLOAD_TOO_LARGE', 'Payload exceeds limit; use smaller pages.'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}
export function redact(value, secrets = []) {
  if (typeof value === 'string') {
    for (const secret of secrets.filter(Boolean)) value = value.split(secret).join('[REDACTED]');
    return value.replace(/Bearer\s+[^\s"<>]+/gi, 'Bearer [REDACTED]');
  }
  if (Array.isArray(value)) return value.map(v => redact(v, secrets));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k,v]) => [k, /^(authorization|cookie|set-cookie|password|access_token|refresh_token|admin_token|api_key)$/i.test(k) ? '[REDACTED]' : redact(v, secrets)]));
  return value;
}
// Publication state reported by a product read, or null when it cannot be determined.
export function publicationState(data) {
  const product = data?.data?.product ?? data?.product ?? data?.data ?? data;
  if (!product || typeof product !== 'object') return null;
  if (product.is_published !== undefined && product.is_published !== null) return Number(product.is_published);
  if ('published_at' in product) return product.published_at ? 1 : 0;
  return null;
}
// The worker may unpublish products but never publish them. A non-zero is_published
// on update is allowed only when it leaves the product's current state unchanged.
async function assertNotPublishing(op, path, body, headers, fetcher) {
  if (op.id !== 'update_product' || body.is_published === 0) return;
  const { 'idempotency-key': _, ...readHeaders } = headers;
  let current;
  try {
    const response = await fetcher(new URL(path, 'https://api.easystore.co'), { method: 'GET', headers: readHeaders, redirect: 'manual', signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error();
    current = publicationState(JSON.parse(await readLimited(response, MAX_RESPONSE)));
  } catch (error) {
    if (error instanceof ToolError) throw error;
    current = null;
  }
  if (current === null) throw new ToolError('PUBLISH_NOT_PERMITTED', 'Could not confirm the product is already published. Publishing is not permitted; set is_published to 0 or retry.');
  if (current !== body.is_published) throw new ToolError('PUBLISH_NOT_PERMITTED', 'Publishing products is not permitted. is_published must be 0 or match the product\'s current state.');
}
export async function execute(env, registry, args, { write = false, fetcher = fetch, audit = console.log } = {}) {
  const requestId = crypto.randomUUID();
  const { op, path, query, body } = resolveOperation(registry, args, write);
  if (write && env.ENABLE_WRITES !== 'true') throw new ToolError('WRITES_DISABLED', 'Writes are disabled by the operator.');
  if (!env.EASYSTORE_ADMIN_TOKEN || env.EASYSTORE_STORE_DOMAIN !== STORE || !/^\d+$/.test(env.EASYSTORE_POD_ID ?? '')) throw new ToolError('CONFIGURATION_ERROR', 'Admin token, store domain and pod must be configured.');
  const mode = env.EASYSTORE_ADMIN_AUTH_MODE ?? 'bearer';
  if (!['bearer','access-token'].includes(mode)) throw new ToolError('CONFIGURATION_ERROR', 'Unsupported admin authentication mode.');
  const url = new URL(path, 'https://api.easystore.co');
  for (const [k,v] of Object.entries(query)) {
    if (v === null || typeof v === 'object') throw new ToolError('INVALID_ARGUMENTS', 'Query values must be scalar.');
    url.searchParams.set(k, String(v));
  }
  const headers = {
    Accept: 'application/json',
    ...(mode === 'bearer' ? { Authorization: `Bearer ${env.EASYSTORE_ADMIN_TOKEN}` } : { 'EasyStore-Access-Token': env.EASYSTORE_ADMIN_TOKEN }),
    'easystore-pod-id': env.EASYSTORE_POD_ID,
    'easystore-source': 'admin',
    'x-easystore-infra-default-domain': STORE,
    'x-easystore-infra-pod-id': env.EASYSTORE_POD_ID,
    'x-easystore-infra-source': 'admin'
  };
  if (write) {
    if (!/^[A-Za-z0-9_-]{16,128}$/.test(args.idempotency_key ?? '')) throw new ToolError('INVALID_ARGUMENTS', 'Writes require a stable 16–128 character idempotency_key.');
    headers['idempotency-key'] = `phase1-dummy:web:${args.idempotency_key}`;
  }
  const serialized = body === undefined ? undefined : JSON.stringify(body);
  if (serialized && new TextEncoder().encode(serialized).length > 256 * 1024) throw new ToolError('PAYLOAD_TOO_LARGE', 'Request body exceeds 256 KiB.');
  if (write) await assertNotPublishing(op, path, body, headers, fetcher);
  if (serialized !== undefined) headers['Content-Type'] = 'application/json';
  let status, outcome = 'failed';
  try {
    // No automatic retry. An upstream timeout may follow a successful mutation.
    const response = await fetcher(url, { method: op.method, headers, body: serialized, redirect: 'manual', signal: AbortSignal.timeout(20000) });
    status = response.status;
    if ([401,403].includes(status)) throw new ToolError('ADMIN_AUTH_REJECTED', 'EasyStore rejected the admin credential: expired, revoked, or insufficient permissions.');
    if (status >= 300 && status < 400) throw new ToolError('UPSTREAM_REDIRECT', 'EasyStore redirected the request; redirect was blocked.');
    if (!response.ok) throw new ToolError('UPSTREAM_ERROR', `EasyStore returned HTTP ${status}. No retry was attempted.`);
    const text = await readLimited(response, MAX_RESPONSE);
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch { throw new ToolError('UPSTREAM_NON_JSON', 'EasyStore did not return JSON.'); }
    }
    outcome = 'success';
    return { request_id: requestId, operation_id: op.id, status, data: redact(data, [env.EASYSTORE_ADMIN_TOKEN, env.MCP_READ_TOKEN, env.MCP_WRITE_TOKEN]) };
  } catch (error) {
    if (error instanceof ToolError) throw error;
    throw new ToolError('UPSTREAM_UNCERTAIN', write ? 'Upstream request failed or timed out. The mutation may have succeeded; inspect the resource before retrying.' : 'Upstream request failed or timed out.');
  } finally {
    // No URL parameters, bodies, tokens, customer details or upstream errors in logs.
    audit(JSON.stringify({ request_id: requestId, actor: write ? 'mcp-writer' : 'mcp-reader', operation_id: op.id, method: op.method, status, outcome }));
  }
}

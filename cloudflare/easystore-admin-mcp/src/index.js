import { McpServer } from '@modelcontextprotocol/server';
import { createMcpHandler } from 'agents/mcp/server';
import { z } from 'zod';
import endpointCatalog from './admin-endpoints.json' with { type: 'json' };
import { ToolError, makeRegistry, isRead } from './registry.js';
import { execute, readLimited } from './easystore.js';

const registry = makeRegistry();
const bag = z.record(z.string(), z.unknown());
const operationArgs = {
  operation_id: z.string().max(64),
  path: bag.optional(),
  query: bag.optional(),
  body: bag.optional()
};
const result = data => ({ content: [{ type: 'text', text: JSON.stringify(data) }] });
const fail = error => ({ isError: true, ...result({ error: error instanceof ToolError ? error.code : 'INTERNAL_ERROR', message: error instanceof ToolError ? error.message : 'Operation failed.' }) });
export async function authenticate(request, env) {
  const value = request.headers.get('Authorization') ?? '';
  if (!value.startsWith('Bearer ')) return null;
  const token = value.slice(7);
  // Hash comparisons prevent timing leaks from token prefixes.
  const digest = async s => new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
  const matches = async expected => {
    if (!expected || expected.length < 32) return false;
    const [a,b] = await Promise.all([digest(token), digest(expected)]);
    let difference = 0;
    for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
    return difference === 0;
  };
  if (env.MCP_READ_TOKEN === env.MCP_WRITE_TOKEN) return null;
  if (await matches(env.MCP_WRITE_TOKEN)) return 'write';
  if (await matches(env.MCP_READ_TOKEN)) return 'read';
  return null;
}
export function createServer(env, role) {
  const server = new McpServer({ name: 'cc-easystore-admin', version: '0.1.0' });
  server.registerTool('easystore_admin_search_endpoints', {
    description: 'Search the static admin frontend route catalog. Catalog entries are source-confirmed routes, not permission grants or complete server schemas. Use list_operations for executable operations.',
    inputSchema: { search: z.string().max(128).optional(), method: z.enum(['GET','POST','PUT','PATCH','DELETE']).optional(), offset: z.number().int().min(0).default(0), limit: z.number().int().min(1).max(50).default(25) },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  }, async ({search,method,offset,limit}) => {
    const rows = endpointCatalog.filter(e => (!method || e.method === method) && (!search || `${e.path} ${e.frontend_operations.join(' ')}`.toLowerCase().includes(search.toLowerCase())));
    return result({total:rows.length,offset,entries:rows.slice(offset,offset+limit).map(e => {
      const normalize = p => p.replace(/\{[^}]+\}/g,'{id}');
      const op = [...registry.values()].find(op => op.method === e.method && normalize(op.path) === normalize(e.path));
      return {...e,operation_id:op?.id ?? null,executable:!!op?.enabled && (isRead(op) || (role === 'write' && env.ENABLE_WRITES === 'true'))};
    })});
  });
  server.registerTool('easystore_admin_list_operations', {
    description: 'Search enabled EasyStore admin operations. Calls are limited to this registry.',
    inputSchema: { search: z.string().max(128).optional() },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  }, async ({ search }) => result([...registry.values()].filter(op => op.enabled && (isRead(op) || (role === 'write' && env.ENABLE_WRITES === 'true')) && (!search || `${op.id} ${op.description}`.toLowerCase().includes(search.toLowerCase()))).map(({id,method,description}) => ({id,method,description}))));
  server.registerTool('easystore_admin_describe_operation', {
    description: 'Get the exact path, query, and JSON body schemas for an enabled operation before calling it.',
    inputSchema: { operation_id: z.string().max(64) },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  }, async ({ operation_id }) => {
    const op = registry.get(operation_id);
    if (!op?.enabled || (!isRead(op) && (role !== 'write' || env.ENABLE_WRITES !== 'true'))) return fail(new ToolError('OPERATION_UNAVAILABLE','Operation is unknown or disabled.'));
    return result(op);
  });
  server.registerTool('easystore_admin_read', {
    description: 'Execute an enabled GET operation using its operation_id. Fetch one page at a time.',
    inputSchema: operationArgs,
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: true }
  }, async args => { try { return result(await execute(env, registry, args)); } catch (e) { return fail(e); } });
  if (role === 'write' && env.ENABLE_WRITES === 'true') server.registerTool('easystore_admin_write', {
    description: 'Execute an enabled admin mutation. Obtain human approval in Viktor before calling. Reuse idempotency_key only for the same intended request. A timeout does not prove failure.',
    inputSchema: { ...operationArgs, idempotency_key: z.string().regex(/^[A-Za-z0-9_-]{16,128}$/) },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true }
  }, async args => { try { return result(await execute(env, registry, args, { write: true })); } catch (e) { return fail(e); } });
  return server;
}
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET') return Response.json({ ok: true, service: 'cc-easystore-admin-mcp' });
    if (url.pathname !== '/mcp') return new Response('Not found', { status: 404 });
    const role = await authenticate(request, env);
    if (!role) return new Response('Bearer connector key required', { status: 401, headers: { 'WWW-Authenticate': 'Bearer realm="cc-easystore-admin"', 'Cache-Control': 'no-store' } });
    // No browser origins by default. Add explicit exact origins if a browser client is needed.
    const origin = request.headers.get('Origin');
    if (origin && origin !== url.origin) return new Response('Origin rejected', { status: 403 });
    let forward = request;
    if (request.method === 'POST') {
      try {
        const text = await readLimited(request, 320 * 1024);
        forward = new Request(request, { body: text });
      } catch (e) { return new Response('Request exceeds 320 KiB', { status: 413 }); }
    }
    const handler = createMcpHandler(() => createServer(env, role), { route: '/mcp', legacy: 'stateless', responseMode: 'json', corsOptions: false, allowedHostnames: [url.hostname], allowedOriginHostnames: [url.hostname] });
    const response = await handler(forward, env, ctx);
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', 'no-store');
    return new Response(response.body, { status: response.status, headers });
  }
};

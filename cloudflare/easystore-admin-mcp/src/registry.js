import { Validator } from '@cfworker/json-schema';
import operations from './operations.json' with { type: 'json' };

export class ToolError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
export const emptyObject = { type: 'object', properties: {}, additionalProperties: false };
export const isRead = op => op.method === 'GET';
export function validate(schema, value, label) {
  const result = new Validator(schema).validate(value);
  if (!result.valid) throw new ToolError('INVALID_ARGUMENTS', `${label} does not match the operation schema.`);
}
export function validateRegistry(items) {
  if (!Array.isArray(items)) throw new Error('Registry must be an array.');
  const ids = new Set();
  for (const op of items) {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(op.id) || ids.has(op.id)) throw new Error('Invalid or duplicate operation id.');
    ids.add(op.id);
    if (!['GET','POST','PUT','PATCH','DELETE'].includes(op.method)) throw new Error('Unsupported method.');
    if (typeof op.enabled !== 'boolean' || !op.description || !op.source) throw new Error('Operation requires enabled, description and source.');
    if (!/^\/admin\/v2\/store\/[A-Za-z0-9_/{}/-]+$/.test(op.path) || /[.\\%?#]|\/\//.test(op.path)) throw new Error('Unsafe operation path.');
    const names = [...op.path.matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map(m => m[1]);
    const schema = op.pathSchema ?? emptyObject;
    if (names.length !== Object.keys(schema.properties ?? {}).length || names.some(n => !schema.properties?.[n] || !schema.required?.includes(n))) throw new Error('Path parameters must have required schemas.');
    for (const s of [schema, op.querySchema ?? emptyObject, op.bodySchema]) {
      if (!s) continue;
      if (s.type !== 'object' || s.additionalProperties !== false) throw new Error('Top-level schemas must be closed objects.');
      new Validator(s);
    }
    validate({ ...(op.querySchema ?? emptyObject), required: [] }, op.queryDefaults ?? {}, 'queryDefaults');
    if (isRead(op) && op.bodySchema) throw new Error('GET cannot have a request body.');
    if (!isRead(op) && op.enabled && !op.bodySchema && op.method !== 'DELETE') throw new Error('Enabled writes require a body schema.');
  }
  return items;
}
export function makeRegistry(items = operations) {
  validateRegistry(items);
  return new Map(items.map(op => [op.id, op]));
}
export function resolveOperation(registry, args, write) {
  const op = registry.get(args.operation_id);
  if (!op?.enabled) throw new ToolError('OPERATION_UNAVAILABLE', 'Operation is unknown or disabled.');
  if (isRead(op) === write) throw new ToolError('WRONG_TOOL', `Use easystore_admin_${isRead(op) ? 'read' : 'write'} for this operation.`);
  validate(op.pathSchema ?? emptyObject, args.path ?? {}, 'path');
  const query = { ...op.queryDefaults, ...args.query };
  validate(op.querySchema ?? emptyObject, query, 'query');
  if (op.bodySchema) validate(op.bodySchema, args.body, 'body');
  else if (args.body !== undefined) throw new ToolError('INVALID_ARGUMENTS', 'This operation has no body.');
  const path = op.path.replace(/\{([^}]+)\}/g, (_, key) => {
    const value = String(args.path[key]);
    // Do not allow encoded separators, dot segments, or alternate store routing.
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(value)) throw new ToolError('INVALID_ARGUMENTS', 'Unsafe path parameter.');
    return value;
  });
  return { op, path, query, body: args.body };
}

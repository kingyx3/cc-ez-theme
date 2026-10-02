// Shape-only discovery: never persist headers, cookies, examples, or response data.
import { createHash } from 'node:crypto';
import { emptyObject } from '../src/registry.js';

export function inferSchema(value, depth = 0) {
  if (depth > 12) return {};
  if (value === null) return { type: 'null' };
  if (Array.isArray(value)) return { type: 'array', items: value.length ? mergeSchemas(value.map(v => inferSchema(v, depth + 1))) : {} };
  if (typeof value === 'object') {
    const properties = Object.fromEntries(Object.entries(value).map(([k,v]) => [k, inferSchema(v, depth + 1)]));
    // Observed keys are not proof of required fields. Review before enabling.
    return { type: 'object', properties, additionalProperties: false };
  }
  return { type: typeof value === 'number' ? (Number.isInteger(value) ? 'integer' : 'number') : typeof value };
}
export function mergeSchemas(schemas) {
  const unique = [...new Map(schemas.map(s => [JSON.stringify(s),s])).values()];
  if (unique.length === 1) return unique[0];
  if (unique.every(s => s.type === 'object')) {
    const keys = [...new Set(unique.flatMap(s => Object.keys(s.properties ?? {})))];
    return { type: 'object', properties: Object.fromEntries(keys.map(k => [k, mergeSchemas(unique.filter(s => s.properties?.[k]).map(s => s.properties[k]))])), additionalProperties: false };
  }
  return { anyOf: unique };
}
const sensitiveQuery = /token|secret|password|authorization|cookie|api.?key/i;
export function candidateFromRequest({ url: rawUrl, method, body, mimeType, status }) {
  let url;
  try { url = new URL(rawUrl); } catch { return null; }
  if (url.origin !== 'https://api.easystore.co' || !url.pathname.startsWith('/admin/v2/store/') || !['GET','POST','PUT','PATCH','DELETE'].includes(method)) return null;
  const pathProperties = {};
  let index = 0;
  const segments = url.pathname.split('/').map(segment => {
    // Only automatic numeric / UUID IDs. Other identifiers remain literal and need review.
    if (/^\d+$|^[a-f0-9]{8}-[a-f0-9-]{27,}$/i.test(segment)) {
      const key = `id_${++index}`;
      pathProperties[key] = { type: 'string', pattern: '^[A-Za-z0-9_-]{1,128}$' };
      return `{${key}}`;
    }
    return segment;
  });
  const route = segments.join('/');
  const digest = createHash('sha256').update(`${method} ${route}`).digest('hex').slice(0,16);
  const queryProperties = Object.fromEntries([...new Set(url.searchParams.keys())].filter(k => !sensitiveQuery.test(k)).map(k => [k,{ type:'string', maxLength:2048 }]));
  let schema;
  let reviewNotes = [];
  if (body && (mimeType ?? '').includes('json')) {
    try { schema = inferSchema(JSON.parse(body)); } catch { reviewNotes.push('Unparseable JSON; no body schema inferred.'); }
  } else if (body) reviewNotes.push('Non-JSON body is unsupported by this Worker; implement a typed adapter.');
  if (schema?.type !== 'object' && schema) { schema = undefined; reviewNotes.push('Non-object JSON body requires a typed adapter.'); }
  if (Object.keys(queryProperties).length !== [...new Set(url.searchParams.keys())].length) reviewNotes.push('Sensitive query parameter omitted; review authentication separately.');
  if (!/^[A-Za-z0-9_/{}/-]+$/.test(route) || /\/\//.test(route)) reviewNotes.push('Path requires manual normalization.');
  return {
    id: `observed_${method.toLowerCase()}_${digest}`,
    method, path: route, description: `Observed ${method} admin operation. Review semantics and schemas before enabling.`, enabled: false,
    source: 'local admin traffic capture (shape only)',
    ...(index ? { pathSchema: { type:'object', properties:pathProperties, required:Object.keys(pathProperties), additionalProperties:false } } : {}),
    ...(Object.keys(queryProperties).length ? { querySchema:{ type:'object', properties:queryProperties, additionalProperties:false } } : {}),
    ...(schema ? { bodySchema:schema } : {}),
    observedStatuses: status ? [status] : [],
    reviewNotes
  };
}
export function mergeCandidates(candidates) {
  const groups = new Map();
  for (const op of candidates.filter(Boolean)) {
    const old = groups.get(op.id);
    if (!old) { groups.set(op.id, op); continue; }
    for (const key of ['querySchema','bodySchema']) if (op[key]) old[key] = mergeSchemas([old[key] ?? emptyObject, op[key]]);
    old.observedStatuses = [...new Set([...old.observedStatuses,...op.observedStatuses])];
    old.reviewNotes = [...new Set([...old.reviewNotes,...op.reviewNotes])];
  }
  return [...groups.values()].sort((a,b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method));
}

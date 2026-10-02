import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { candidateFromRequest, mergeCandidates } from './discovery.js';
export function importHar(har) {
  if (!Array.isArray(har.log?.entries)) throw new Error('Not a HAR file.');
  return mergeCandidates(har.log.entries.map(entry => candidateFromRequest({ url:entry.request.url, method:entry.request.method, body:entry.request.postData?.text, mimeType:entry.request.postData?.mimeType, status:entry.response?.status })));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [input, output = 'captures/operations.pending.json'] = process.argv.slice(2);
  if (!input) throw new Error('Usage: npm run import:har -- local.har [output.json]');
  const candidates = importHar(JSON.parse(await readFile(input,'utf8')));
  await mkdir(dirname(output), { recursive:true });
  await writeFile(output, JSON.stringify(candidates,null,2)+'\n', { mode:0o600 });
  console.log(`Wrote ${candidates.length} disabled operation candidates. No raw request/response values or headers were copied. Review route identifiers and property names before sharing.`);
}

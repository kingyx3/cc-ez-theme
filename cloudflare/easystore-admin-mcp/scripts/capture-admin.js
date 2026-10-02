import { chromium } from 'playwright';
import { writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { candidateFromRequest, mergeCandidates } from './discovery.js';

const output = process.argv[2] ?? 'captures/operations.pending.json';
const browser = await chromium.launch({ headless:false });
// Ephemeral profile. Authentication stays in browser memory, never an exported file.
const context = await browser.newContext();
const observations = [];
const pending = new Set();
context.on('response', response => {
  const request = response.request();
  const candidate = candidateFromRequest({ url:request.url(), method:request.method(), body:request.postData(), mimeType:request.headers()['content-type'], status:response.status() });
  if (candidate) observations.push(candidate);
});
// Collect literal admin routes from JS bundles loaded during the session.
// These are hints only: no methods or payload schemas are asserted.
const bundleRoutes = new Set();
context.on('response', response => {
  if (response.request().resourceType() !== 'script') return;
  let hostname;
  try { hostname = new URL(response.url()).hostname; } catch { return; }
  if (!/(^|\.)easystore\.co$/.test(hostname)) return;
  const job = (async () => {
    try {
      const code = await response.text();
      for (const match of code.matchAll(/\/admin\/v2\/store\/[A-Za-z0-9_/{}/-]+/g)) bundleRoutes.add(match[0]);
    } catch { /* Lazy assets may disappear as pages navigate. */ }
  })();
  pending.add(job); job.finally(() => pending.delete(job));
});
const page = await context.newPage();
await page.goto('https://admin.easystore.co/');
console.log('Sign in yourself. Open sections and forms normally. Capture does not click buttons, submit forms, or replay requests.');
console.log('When finished, press Enter here. Do not create/delete production data solely for discovery.');
const readline = createInterface({ input:process.stdin, output:process.stdout });
await readline.question('');
readline.close();
await Promise.allSettled([...pending]);
await mkdir(dirname(output),{ recursive:true });
await writeFile(output,JSON.stringify(mergeCandidates(observations),null,2)+'\n',{ mode:0o600 });
await writeFile(output.replace(/\.json$/, '')+'.bundle-routes.json',JSON.stringify([...bundleRoutes].sort(),null,2)+'\n',{ mode:0o600 });
await browser.close();
console.log(`Wrote ${mergeCandidates(observations).length} disabled operations and ${bundleRoutes.size} bundle route hints. Review route identifiers/property names before sharing; credentials and data values are not exported.`);

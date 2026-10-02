import { readdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { makeRegistry } from '../src/registry.js';
import catalog from '../src/admin-endpoints.json' with { type: 'json' };
for (const directory of ['src','scripts','test']) {
  for (const file of await readdir(directory)) if (file.endsWith('.js')) {
    const checked = spawnSync(process.execPath,['--check',`${directory}/${file}`],{ stdio:'inherit' });
    if (checked.status !== 0) process.exit(1);
  }
}
makeRegistry();
const seen = new Set();
for (const entry of catalog) {
  const key = `${entry.method} ${entry.path}`;
  if (seen.has(key) || !['GET','POST','PUT','PATCH','DELETE'].includes(entry.method) || !/^\/admin\/v2\/store\/[A-Za-z0-9_/{}/-]+$/.test(entry.path) || !Array.isArray(entry.frontend_operations) || !entry.source?.startsWith('https://admin.easystore.co/assets/')) throw new Error('Invalid or duplicate static catalog entry.');
  seen.add(key);
}
console.log(`JavaScript, operation registry and ${catalog.length} static endpoints valid.`);

import { readdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { makeRegistry } from '../src/registry.js';
for (const directory of ['src','scripts','test']) {
  for (const file of await readdir(directory)) if (file.endsWith('.js')) {
    const checked = spawnSync(process.execPath,['--check',`${directory}/${file}`],{ stdio:'inherit' });
    if (checked.status !== 0) process.exit(1);
  }
}
makeRegistry();
console.log('JavaScript and operation registry valid.');

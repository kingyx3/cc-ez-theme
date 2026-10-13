import { pathToFileURL } from 'node:url';
import { smokeTest } from './deploy.js';

export const WORKER_ORIGIN = 'https://cc-easystore-admin-mcp.cardboardsg.workers.dev';

// Keep the host fixed; never forward the production connector key to a user-provided URL.
export async function checkHostedMcp(readToken, fetcher = fetch) {
  if (!readToken) throw new Error('Missing production MCP read token.');
  return smokeTest(WORKER_ORIGIN, { MCP_READ_TOKEN: readToken, LIVE_READ_CHECKS: 'true' }, fetcher);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  checkHostedMcp(process.env.MCP_READ_TOKEN)
    .then(checks => console.log(['Production MCP authenticated health check: passed', ...checks].join('\n')))
    .catch(error => { console.error(error instanceof Error ? error.message : 'MCP health check failed.'); process.exitCode = 1; });
}

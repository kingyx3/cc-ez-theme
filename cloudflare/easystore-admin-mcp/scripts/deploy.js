import { execFileSync } from 'node:child_process';
import { mkdtemp, writeFile, rm, appendFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readLimited } from '../src/easystore.js';

export async function readRpcResponse(response, id) {
  try {
    const text = await readLimited(response, 2 * 1024 * 1024);
    const messages = response.headers.get('content-type')?.includes('text/event-stream')
      ? text.split(/\r?\n\r?\n/).flatMap(event => {
          const data = event.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
          return data ? [JSON.parse(data)] : [];
        })
      : [JSON.parse(text)];
    const message = messages.find(message => message.id === id);
    if (!message || (!message.result && !message.error)) throw new Error();
    return message;
  } catch { throw new Error('Hosted MCP returned an invalid or oversized RPC response.'); }
}

export function deploymentConfig(env) {
  for (const key of ['CLOUDFLARE_API_TOKEN','CLOUDFLARE_ACCOUNT_ID','EASYSTORE_ADMIN_TOKEN','MCP_READ_TOKEN','MCP_WRITE_TOKEN']) if (!env[key]) throw new Error(`Missing GitHub secret: ${key}`);
  if (env.MCP_READ_TOKEN.length < 32 || env.MCP_WRITE_TOKEN.length < 32 || env.MCP_READ_TOKEN === env.MCP_WRITE_TOKEN) throw new Error('Connector keys must be distinct and at least 32 characters.');
  if (!['true','false'].includes(env.ENABLE_WRITES ?? 'false')) throw new Error('ENABLE_WRITES must be true or false.');
  return { enableWrites:env.ENABLE_WRITES ?? 'false', secrets:{EASYSTORE_ADMIN_TOKEN:env.EASYSTORE_ADMIN_TOKEN,MCP_READ_TOKEN:env.MCP_READ_TOKEN,MCP_WRITE_TOKEN:env.MCP_WRITE_TOKEN} };
}
export async function smokeTest(url, env, fetcher = fetch) {
  const base = new URL(url);
  if (base.protocol !== 'https:' || !base.hostname.endsWith('.workers.dev')) throw new Error('Expected the workers.dev URL returned by Wrangler.');
  const response = await fetcher(new URL('/mcp',base), {method:'POST',headers:{Authorization:`Bearer ${env.MCP_READ_TOKEN}`,'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/list',params:{}}),redirect:'manual',signal:AbortSignal.timeout(20000)});
  if(!response.ok) throw new Error(`Hosted MCP smoke test failed: HTTP ${response.status}.`);
  const json=await readRpcResponse(response,1);
  if(json.error || !json.result?.tools?.some(t=>t.name==='easystore_admin_read'))throw new Error('Hosted MCP tools/list failed.');
  const outcomes=[];
  if(env.LIVE_READ_CHECKS === 'true') {
    for(const operation_id of ['list_products','list_customers','list_discounts_new']) {
      const read=await fetcher(new URL('/mcp',base),{method:'POST',headers:{Authorization:`Bearer ${env.MCP_READ_TOKEN}`,'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/call',params:{name:'easystore_admin_read',arguments:{operation_id,query:{limit:1,page:1}}}}),redirect:'manual',signal:AbortSignal.timeout(25000)});
      if(!read.ok)throw new Error(`Live read ${operation_id} failed: HTTP ${read.status}.`);
      const result=await readRpcResponse(read,2);
      if(result.error || result.result?.isError) {
        // Report a fixed error code only; never log response records or messages.
        let code='TOOL_ERROR';try{code=JSON.parse(result.result.content[0].text).error??code}catch{}
        throw new Error(`Live read ${operation_id} failed (${/^[A-Z_]+$/.test(code)?code:'TOOL_ERROR'}).`);
      }
      if(!result.result?.content?.length)throw new Error(`Live read ${operation_id} returned an invalid result.`);
      outcomes.push(`${operation_id}: passed`);
    }
  }
  return outcomes;
}
export async function deploy(env = process.env, run = (args) => execFileSync(process.execPath, ['node_modules/wrangler/bin/wrangler.js',...args], {encoding:'utf8',env,maxBuffer:4*1024*1024,stdio:['ignore','pipe','pipe']})) {
  const config=deploymentConfig(env);
  const directory=await mkdtemp(join(env.RUNNER_TEMP ?? process.cwd(), 'easystore-admin-secrets-'));
  try {
    const file=join(directory,'secrets.json');
    await writeFile(file,JSON.stringify(config.secrets),{mode:0o600});
    let stdout;
    try { stdout=run(['deploy','--secrets-file',file,'--var',`ENABLE_WRITES:${config.enableWrites}`]); }
    catch { throw new Error('Cloudflare deployment failed. Check Cloudflare token/account permissions and Worker configuration. No credential output was printed.'); }
    const url=stdout.match(/https:\/\/cc-easystore-admin-mcp\.[a-z0-9-]+\.workers\.dev/i)?.[0];
    if(!url)throw new Error('Worker deployed, but Wrangler did not return its workers.dev URL. Check the Cloudflare dashboard.');
    const checks=await smokeTest(url,env);
    const summary=`## EasyStore admin MCP\n\n- MCP URL: ${url}/mcp\n- Hosted authenticated tools/list: passed\n- Writes: ${config.enableWrites === 'true'?'enabled for registered operations':'disabled'}\n${checks.map(s=>'- '+s+'\n').join('')}\nUse the read or writer connector key in Viktor’s secure credential field.\n`;
    if(env.GITHUB_STEP_SUMMARY)await appendFile(env.GITHUB_STEP_SUMMARY,summary);
    console.log(summary);
    return {url,checks};
  } finally {await rm(directory,{recursive:true,force:true});}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)deploy().catch(e=>{console.error(e.message);process.exitCode=1});

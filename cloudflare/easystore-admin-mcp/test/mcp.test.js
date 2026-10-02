import test from 'node:test';
import assert from 'node:assert/strict';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { readRpcResponse } from '../scripts/deploy.js';

const readToken='r'.repeat(48),writeToken='w'.repeat(48);
const bindings={MCP_READ_TOKEN:readToken,MCP_WRITE_TOKEN:writeToken,EASYSTORE_ADMIN_TOKEN:'test-only-admin',EASYSTORE_STORE_DOMAIN:'cardboardcollective.easy.co',EASYSTORE_POD_ID:'1007',ENABLE_WRITES:'false'};
function runtime(overrides={}) {
  return new Miniflare(convertV4MiniflareOptions({modules:true,scriptPath:'dist/index.js',compatibilityDate:'2026-08-20',compatibilityFlags:['nodejs_compat'],bindings:{...bindings,...overrides}}));
}
async function connect(mf,token) {
  const client=new Client({name:'test-viktor-client',version:'1.0.0'});
  const transport=new StreamableHTTPClientTransport(new URL('http://127.0.0.1/mcp'),{requestInit:{headers:{Authorization:`Bearer ${token}`}},fetch:(url,init)=>mf.dispatchFetch(url,init)});
  await client.connect(transport);
  return client;
}
test('real MCP SDK initializes, discovers tools, describes operations, and rejects unavailable calls',async()=>{
  const mf=runtime();let client;
  try {
    assert.equal((await mf.dispatchFetch('http://127.0.0.1/mcp')).status,401);
    assert.equal((await mf.dispatchFetch('http://127.0.0.1/mcp',{headers:{Authorization:'Bearer wrong'}})).status,401);
    assert.equal((await mf.dispatchFetch('http://127.0.0.1/mcp',{headers:{Authorization:`Bearer ${readToken}`,Origin:'https://evil.test'}})).status,403);
    client=await connect(mf,readToken);
    const tools=await client.listTools();
    assert.deepEqual(tools.tools.map(t=>t.name).sort(),['easystore_admin_describe_operation','easystore_admin_list_operations','easystore_admin_read']);
    assert.ok(tools.tools.every(t=>t.annotations.readOnlyHint));
    const list=await client.callTool({name:'easystore_admin_list_operations',arguments:{}});
    assert.ok(JSON.parse(list.content[0].text).some(o=>o.id==='list_discounts_new'));
    const direct=await mf.dispatchFetch('http://127.0.0.1/mcp',{method:'POST',headers:{Authorization:`Bearer ${readToken}`,'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify({jsonrpc:'2.0',id:42,method:'tools/list',params:{}})});
    assert.ok((await readRpcResponse(direct,42)).result.tools.length>=3);
    const description=await client.callTool({name:'easystore_admin_describe_operation',arguments:{operation_id:'list_abandoned_checkouts'}});
    assert.equal(JSON.parse(description.content[0].text).querySchema.properties.limit.maximum,50);
    const blocked=await client.callTool({name:'easystore_admin_read',arguments:{operation_id:'publish_theme'}});
    assert.equal(blocked.isError,true);
  } finally { if(client)await client.close();await mf.dispose(); }
});
test('write tool requires the separate writer credential and server toggle',async()=>{
  const mf=runtime({ENABLE_WRITES:'true'});let reader,writer;
  try {
    reader=await connect(mf,readToken);writer=await connect(mf,writeToken);
    assert.ok(!(await reader.listTools()).tools.some(t=>t.name==='easystore_admin_write'));
    const write=(await writer.listTools()).tools.find(t=>t.name==='easystore_admin_write');
    assert.equal(write.annotations.readOnlyHint,false);
    assert.equal(write.annotations.destructiveHint,true);
    assert.equal(write.annotations.idempotentHint,false);
  } finally {if(reader)await reader.close();if(writer)await writer.close();await mf.dispose();}
});

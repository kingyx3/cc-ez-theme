import test from 'node:test';
import assert from 'node:assert/strict';
import { deploymentConfig, smokeTest, readRpcResponse } from '../scripts/deploy.js';
const env={CLOUDFLARE_API_TOKEN:'test-cf',CLOUDFLARE_ACCOUNT_ID:'test-account',EASYSTORE_ADMIN_TOKEN:'test-admin',MCP_READ_TOKEN:'r'.repeat(40),MCP_WRITE_TOKEN:'w'.repeat(40),ENABLE_WRITES:'false'};
test('GHA validates credentials and distinct connector keys before deployment',()=>{
  assert.equal(deploymentConfig(env).enableWrites,'false');
  assert.throws(()=>deploymentConfig({...env,CLOUDFLARE_API_TOKEN:''}),/CLOUDFLARE_API_TOKEN/);
  assert.throws(()=>deploymentConfig({...env,MCP_WRITE_TOKEN:env.MCP_READ_TOKEN}),/distinct/);
  assert.throws(()=>deploymentConfig({...env,ENABLE_WRITES:'yes'}),/true or false/);
});
test('hosted smoke tests authenticate and report status only, not customer data',async()=>{
  let calls=0;
  const checks=await smokeTest('https://cc-easystore-admin-mcp.test.workers.dev',{...env,LIVE_READ_CHECKS:'true'},async(url,init)=>{
    calls++;assert.equal(init.headers.Authorization,`Bearer ${env.MCP_READ_TOKEN}`);
    const request=JSON.parse(init.body);
    if(request.method==='tools/list')return Response.json({id:1,result:{tools:[{name:'easystore_admin_read'}]}});
    assert.equal(request.params.arguments.query.limit,1);
    return Response.json({id:2,result:{content:[{type:'text',text:JSON.stringify({data:{email:'private@example.com'}})}]}});
  });
  assert.equal(calls,4);assert.equal(checks.length,3);assert.ok(!checks.join().includes('private@example.com'));
  await assert.rejects(smokeTest('https://evil.test',env,()=>{}),/workers.dev/);
});
test('live read failures retain actionable error codes without logging upstream content',async()=>{
  await assert.rejects(smokeTest('https://cc-easystore-admin-mcp.test.workers.dev',{...env,LIVE_READ_CHECKS:'true'},async(url,init)=>JSON.parse(init.body).method==='tools/list'?Response.json({id:1,result:{tools:[{name:'easystore_admin_read'}]}}):Response.json({id:2,result:{isError:true,content:[{type:'text',text:JSON.stringify({error:'ADMIN_AUTH_REJECTED',data:'private-customer-data'})}]}})),e=>e.message.includes('ADMIN_AUTH_REJECTED')&&!e.message.includes('private-customer-data'));
});

test('hosted smoke parser supports legacy SSE, skips notifications and rejects invalid RPC',async()=>{
  const body='event: message\ndata: {"jsonrpc":"2.0","method":"notifications/message"}\n\nevent: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n';
  const response=new Response(body,{headers:{'content-type':'text/event-stream'}});
  assert.deepEqual((await readRpcResponse(response,1)).result,{tools:[]});
  await assert.rejects(readRpcResponse(Response.json({id:2,result:{tools:[]}}),1),/invalid/);
  await assert.rejects(readRpcResponse(new Response('private-data'),1),e=>!e.message.includes('private-data'));
});

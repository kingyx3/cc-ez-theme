import test from 'node:test';
import assert from 'node:assert/strict';
import { checkHostedMcp, WORKER_ORIGIN } from '../scripts/healthcheck.js';

test('daily health check always authenticates live list and three read operations', async () => {
  let n=0;
  const checks=await checkHostedMcp('r'.repeat(40),async (url,options)=>{
    n++;
    assert.equal(new URL(url).origin, WORKER_ORIGIN);
    assert.equal(options.headers.Authorization, 'Bearer ' + 'r'.repeat(40));
    const payload=JSON.parse(options.body);
    if (payload.method==='tools/list') return Response.json({id:1,result:{tools:[{name:'easystore_admin_read'}]}});
    return Response.json({id:2,result:{content:[{type:'text',text:'{}'}]}});
  });
  assert.equal(n,4);
  assert.deepEqual(checks, ['list_products: passed','list_customers: passed','list_discounts_new: passed']);
});

test('daily health check fails closed on missing secret and upstream admin rejection', async()=>{
  await assert.rejects(checkHostedMcp(''),/Missing production MCP read token/);
  await assert.rejects(checkHostedMcp('r'.repeat(40),async (url,options)=>{
    const method=JSON.parse(options.body).method;
    return method==='tools/list'
      ? Response.json({id:1,result:{tools:[{name:'easystore_admin_read'}]}})
      : Response.json({id:2,result:{isError:true,content:[{type:'text',text:'{"error":"ADMIN_AUTH_REJECTED","data":"private"}'}]}});
  }),e=>e.message.includes('ADMIN_AUTH_REJECTED')&&!e.message.includes('private'));
});

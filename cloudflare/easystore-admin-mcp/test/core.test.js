import test from 'node:test';
import assert from 'node:assert/strict';
import { execute, redact } from '../src/easystore.js';
import { makeRegistry, resolveOperation, validateRegistry } from '../src/registry.js';

const env = { EASYSTORE_ADMIN_TOKEN:'secret-admin-value', EASYSTORE_STORE_DOMAIN:'cardboardcollective.easy.co', EASYSTORE_POD_ID:'1007', MCP_READ_TOKEN:'secret-reader-value', ENABLE_WRITES:'true' };
const writeOp = { id:'update_widget', method:'PUT', path:'/admin/v2/store/widgets/{id}', enabled:true, description:'Update widget', source:'test', pathSchema:{type:'object',properties:{id:{type:'string'}},required:['id'],additionalProperties:false}, bodySchema:{type:'object',properties:{amount:{type:'integer',minimum:0}},required:['amount'],additionalProperties:false} };
const registry = makeRegistry([writeOp,...makeRegistry().values()]);
const noAudit = () => {};

test('read forwards the exact admin headers, query defaults and fixed origin', async () => {
  const logs = [];
  const output = await execute(env,registry,{operation_id:'list_abandoned_checkouts',query:{page:2}},{audit:line=>logs.push(line),fetcher:async (url, init) => {
    assert.equal(url.origin,'https://api.easystore.co');
    assert.equal(url.pathname,'/admin/v2/store/checkouts');
    assert.equal(url.searchParams.get('page'),'2');
    assert.equal(url.searchParams.get('limit'),'50');
    assert.equal(init.headers.Authorization,'Bearer secret-admin-value');
    assert.equal(init.headers['x-easystore-infra-default-domain'],env.EASYSTORE_STORE_DOMAIN);
    assert.equal(init.redirect,'manual');
    assert.equal(init.body,undefined);
    return Response.json({data:{checkouts:[]},params:{page_count:3}});
  }});
  assert.equal(output.data.params.page_count,3);
  assert.equal(logs.length,1);
  assert.doesNotMatch(logs.join(''),/secret-admin-value|created_at|cardboardcollective/);
});
test('unknown/disabled operations, wrong tools and extra query keys never reach upstream', async () => {
  let calls = 0;
  const options = {fetcher:()=>{calls++;},audit:noAudit};
  for (const args of [{operation_id:'unknown'},{operation_id:'publish_theme'}, {operation_id:'update_widget',path:{id:'1'},body:{amount:1}}, {operation_id:'list_themes',query:{domain:'other.easy.co'}}]) await assert.rejects(execute(env,registry,args,options));
  assert.equal(calls,0);
});
test('path traversal and encoded separators are rejected', () => {
  for (const id of ['..','../settings','%2Fadmin','a/b','a?x=1','a\\b']) assert.throws(()=>resolveOperation(registry,{operation_id:'update_widget',path:{id},body:{amount:1}},true));
  assert.throws(()=>validateRegistry([{...writeOp,path:'/admin/v2/store/../auth/{id}'}]));
});
test('writes enforce toggle, body schema and stable idempotency key', async () => {
  let calls = 0;
  const fetcher = async (url, init) => {
    calls++;
    assert.equal(url.pathname,'/admin/v2/store/widgets/12');
    assert.equal(init.headers['idempotency-key'],'phase1-dummy:web:intent_123456789012');
    assert.deepEqual(JSON.parse(init.body),{amount:89});
    return Response.json({id:'12'});
  };
  const args={operation_id:'update_widget',path:{id:'12'},body:{amount:89},idempotency_key:'intent_123456789012'};
  await assert.rejects(execute({...env,ENABLE_WRITES:'false'},registry,args,{write:true,fetcher,audit:noAudit}),/disabled/);
  await assert.rejects(execute(env,registry,{...args,body:{amount:-1}},{write:true,fetcher,audit:noAudit}),/schema/);
  await assert.rejects(execute(env,registry,{...args,idempotency_key:'short'},{write:true,fetcher,audit:noAudit}),/idempotency/);
  assert.equal(calls,0);
  await execute(env,registry,args,{write:true,fetcher,audit:noAudit});
  assert.equal(calls,1);
});
test('redirects, auth rejection, timeouts, HTTP errors and non-JSON responses are clear and never retried', async () => {
  for (const [status, code] of [[302,'UPSTREAM_REDIRECT'],[401,'ADMIN_AUTH_REJECTED'],[403,'ADMIN_AUTH_REJECTED'],[422,'UPSTREAM_ERROR'],[429,'UPSTREAM_ERROR'],[500,'UPSTREAM_ERROR']]) {
    let calls=0;
    await assert.rejects(execute(env,registry,{operation_id:'list_themes'},{audit:noAudit,fetcher:async()=>{calls++;return new Response('secret-admin-value',{status});}}),e=>e.code===code&&!e.message.includes(env.EASYSTORE_ADMIN_TOKEN));
    assert.equal(calls,1);
  }
  await assert.rejects(execute(env,registry,{operation_id:'update_widget',path:{id:'1'},body:{amount:1},idempotency_key:'intent_123456789012'},{write:true,audit:noAudit,fetcher:async()=>{throw new Error('token secret-admin-value');}}),e=>e.code==='UPSTREAM_UNCERTAIN'&&e.message.includes('may have succeeded'));
  await assert.rejects(execute(env,registry,{operation_id:'list_themes'},{audit:noAudit,fetcher:async()=>new Response('<html/>')}),e=>e.code==='UPSTREAM_NON_JSON');
});
test('response size cap and credential redaction', async () => {
  await assert.rejects(execute(env,registry,{operation_id:'list_themes'},{audit:noAudit,fetcher:async()=>new Response('x'.repeat(2*1024*1024+1))}),e=>e.code==='PAYLOAD_TOO_LARGE');
  const output=await execute(env,registry,{operation_id:'list_themes'},{audit:noAudit,fetcher:async()=>Response.json({authorization:'another secret',note:'secret-admin-value',rows:[{refresh_token:'sensitive'}]})});
  assert.equal(output.data.note,'[REDACTED]');
  assert.equal(output.data.authorization,'[REDACTED]');
  assert.equal(output.data.rows[0].refresh_token,'[REDACTED]');
  assert.equal(redact('Bearer abc'),'Bearer [REDACTED]');
});

test('source-confirmed admin DELETE parameters go in query, without a JSON body',async()=>{
  const actual=makeRegistry();
  await execute(env,actual,{operation_id:'delete_discount',query:{id:42},idempotency_key:'delete_intent_123456'},{write:true,audit:noAudit,fetcher:async(url,init)=>{
    assert.equal(url.pathname,'/admin/v2/store/discounts');assert.equal(url.searchParams.get('id'),'42');
    assert.equal(init.method,'DELETE');assert.equal(init.body,undefined);assert.equal(init.headers['Content-Type'],undefined);
    return Response.json({data:{deleted:true}});
  }});
});
test('promotion create uses a flat editor payload with defaults, explicit targeting and code settings',async()=>{
  const args={operation_id:'create_discount',idempotency_key:'discount_intent_1234',body:{title:'Customer offer',promotion_applies_to:'order_subtotal',target_type:'line_item',value_type:'fixed_amount',value:89,channel_selection:'website',starts_at:'2026-10-02T08:00:00Z',usage_limit:1,usage_limit_per_customer:1,customer_selection:'prerequisite_customer',prerequisite_customer_ids:[42],discount_codes:[{code:'CUSTOMER49'}]}};
  await execute(env,makeRegistry(),args,{write:true,audit:noAudit,fetcher:async(url,init)=>{
    assert.equal(url.pathname,'/admin/v2/store/discounts');const body=JSON.parse(init.body);
    assert.equal(body.title,'Customer offer');assert.equal(body.id,0);assert.equal(body.discount,undefined);
    assert.deepEqual(body.prerequisite_customer_ids,[42]);assert.equal(body.redemption_setting,null);
    return Response.json({data:{discount:{id:101}}});
  }});
  await assert.rejects(execute(env,makeRegistry(),{...args,body:{...args.body,value_type:'percentage',value:101}},{write:true,audit:noAudit}),/100/);
});
test('product update rejects mismatched path/body resource IDs before an upstream write',()=>{
  assert.throws(()=>resolveOperation(makeRegistry(),{operation_id:'update_product',path:{product_id:'100'},body:{id:200}},true),/must match/);
});
test('product positioning uses the admin PATCH endpoint with an ordered unique id list',async()=>{
  const actual=makeRegistry();
  let calls=0;
  const args={operation_id:'update_product_positions',body:{product_ids:[17473183,17067738,17447825]},idempotency_key:'product_position_intent_001'};
  await execute(env,actual,args,{write:true,audit:noAudit,fetcher:async(url,init)=>{
    calls++;
    assert.equal(url.pathname,'/admin/v2/store/products/positions');
    assert.equal(init.method,'PATCH');
    assert.deepEqual(JSON.parse(init.body),{product_ids:[17473183,17067738,17447825]});
    return Response.json({data:{updated:true}});
  }});
  assert.equal(calls,1);
  for (const product_ids of [[],[17473183,17473183],[17473183,'17067738']]) {
    await assert.rejects(execute(env,actual,{...args,body:{product_ids}},{write:true,audit:noAudit,fetcher:async()=>{calls++;}}),/schema/);
  }
  assert.equal(calls,1);
});
test('product create is unpublished-only and cannot set a publication date',async()=>{
  const body={title:'New card',taxable:false,shipping_required:true,inventory_management:'easystore',is_published:0,variants:[{sku:'SKU-1',price:10,taxable:false,shipping_required:true}]};
  let calls=0;
  const fetcher=async(url,init)=>{calls++;assert.equal(init.method,'POST');assert.equal(JSON.parse(init.body).is_published,0);return Response.json({data:{product:{id:1}}});};
  await execute(env,makeRegistry(),{operation_id:'create_product',body,idempotency_key:'create_product_intent_1'},{write:true,audit:noAudit,fetcher});
  assert.equal(calls,1);
  for (const extra of [{is_published:1},{is_published:2},{published_at:'2026-10-06T00:00:00Z'}]) {
    await assert.rejects(execute(env,makeRegistry(),{operation_id:'create_product',body:{...body,...extra},idempotency_key:'create_product_intent_1'},{write:true,audit:noAudit,fetcher}),/schema/);
  }
  assert.equal(calls,1);
});
test('product update can unpublish but never publish',async()=>{
  const body={id:100,title:'Card',taxable:false,shipping_required:true,inventory_management:'easystore',variants:[{sku:'SKU-1',price:10,taxable:false,shipping_required:true}]};
  const run=(is_published,current)=>{
    const calls=[];
    const fetcher=async(url,init)=>{
      calls.push(init.method);
      assert.equal(url.pathname,'/admin/v2/store/products/100');
      if (init.method==='GET') { assert.equal(init.headers['idempotency-key'],undefined); return current instanceof Response?current:Response.json(current); }
      return Response.json({data:{product:{id:100}}});
    };
    return {calls,promise:execute(env,makeRegistry(),{operation_id:'update_product',path:{product_id:'100'},body:{...body,is_published},idempotency_key:'update_product_intent_1'},{write:true,audit:noAudit,fetcher})};
  };
  let r=run(0,null); await r.promise; assert.deepEqual(r.calls,['PUT']);
  r=run(1,{data:{product:{id:100,is_published:1}}}); await r.promise; assert.deepEqual(r.calls,['GET','PUT']);
  r=run(1,{product:{id:100,published_at:'2026-01-01T00:00:00Z'}}); await r.promise; assert.deepEqual(r.calls,['GET','PUT']);
  for (const [value,current] of [[1,{data:{product:{id:100,is_published:0}}}],[1,{product:{id:100,published_at:null}}],[2,{data:{product:{id:100,is_published:1}}}],[1,{data:{product:{id:100}}}],[1,new Response('nope',{status:500})]]) {
    r=run(value,current);
    await assert.rejects(r.promise,e=>e.code==='PUBLISH_NOT_PERMITTED');
    assert.deepEqual(r.calls,['GET']);
  }
});

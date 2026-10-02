import test from 'node:test';
import assert from 'node:assert/strict';
import { execute, redact } from '../src/easystore.js';
import { makeRegistry, resolveOperation, validateRegistry } from '../src/registry.js';
import { candidateFromRequest, mergeCandidates } from '../scripts/discovery.js';
import { importHar } from '../scripts/import-har.js';

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
test('HAR importer only emits shapes, normalizes IDs, merges captures and disables everything', () => {
  const har={log:{entries:[1,2].map(id=>({request:{url:`https://api.easystore.co/admin/v2/store/widgets/${id}?page=3&token=secret`,method:'PUT',headers:[{name:'Authorization',value:'secret'}],postData:{mimeType:'application/json',text:JSON.stringify({email:'person@example.com',amount:89})}},response:{status:200,content:{text:'private-response'}}}))}};
  const candidates=importHar(har);
  assert.equal(candidates.length,1);
  const output=JSON.stringify(candidates);
  for (const privateValue of ['person@example.com','private-response','"89"','token=secret']) assert.ok(!output.includes(privateValue));
  assert.equal(candidates[0].enabled,false);
  assert.equal(candidates[0].path,'/admin/v2/store/widgets/{id_1}');
  assert.equal(candidates[0].bodySchema.properties.amount.type,'integer');
  assert.equal(candidates[0].querySchema.properties.token,undefined);
  validateRegistry(candidates);
  assert.equal(candidateFromRequest({url:'https://evil.test/admin/v2/store/widgets',method:'GET'}),null);
  assert.equal(mergeCandidates([null,...candidates,...candidates]).length,1);
});

test('OpenAPI importer resolves local refs, required query fields and valid property names without retaining examples', async () => {
  const {importOpenApi}=await import('../scripts/import-openapi.js');
  const document={openapi:'3.0.3',servers:[{url:'https://api.easystore.co/admin/v2/store'}],components:{schemas:{Widget:{type:'object',properties:{description:{type:'string',example:'private example'},amount:{type:'integer',minimum:0}},required:['amount']}}},paths:{'/widgets/{id}':{parameters:[{in:'path',name:'id',required:true,schema:{type:'string'}}],put:{parameters:[{in:'query',name:'kind',required:true,schema:{type:'string'}}],requestBody:{content:{'application/json':{schema:{$ref:'#/components/schemas/Widget'}}}}}}}};
  const ops=importOpenApi(document);
  assert.equal(ops.length,1);
  assert.equal(ops[0].bodySchema.properties.description.type,'string');
  assert.ok(!JSON.stringify(ops).includes('private example'));
  const imported=makeRegistry(ops);
  assert.equal(imported.size,1);
  const enabled=makeRegistry(ops.map(op=>({...op,enabled:true})));
  assert.throws(()=>resolveOperation(enabled,{operation_id:ops[0].id,path:{id:'1'},body:{amount:1}},true));
  assert.equal(resolveOperation(enabled,{operation_id:ops[0].id,path:{id:'1'},query:{kind:'simple'},body:{amount:1}},true).path,'/admin/v2/store/widgets/1');
  assert.equal(importOpenApi({...document,servers:[{url:'https://evil.test/admin/v2/store'}]}).length,0);
  assert.throws(()=>importOpenApi({...document,paths:{'/widgets':{get:{parameters:[{$ref:'https://evil.test/schema'}]}}}}),/local/);
});

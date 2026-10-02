import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

function resolve(value, document, seen = new Set()) {
  if (!value || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(v => resolve(v,document,seen));
  if (value.$ref) {
    if (!value.$ref.startsWith('#/') || seen.has(value.$ref)) throw new Error('Only non-cyclic local OpenAPI refs are supported.');
    const target=value.$ref.slice(2).split('/').reduce((v,k)=>v?.[k.replaceAll('~1','/').replaceAll('~0','~')],document);
    if (!target) throw new Error('Unresolved OpenAPI ref.');
    return resolve({...target,...Object.fromEntries(Object.entries(value).filter(([k])=>k!=='$ref'))},document,new Set([...seen,value.$ref]));
  }
  // Strip annotations and example values. The registry retains validation structure.
  return Object.fromEntries(Object.entries(value).filter(([k])=>!['example','examples','default','description','title','externalDocs','xml','discriminator','deprecated','readOnly','writeOnly'].includes(k)&&!k.startsWith('x-')).map(([k,v])=>[k,['properties','$defs','definitions'].includes(k) ? Object.fromEntries(Object.entries(v).map(([name,schema])=>[name,resolve(schema,document,seen)])) : resolve(v,document,seen)]));
}
function closedObject(properties,required=[]) {return {type:'object',properties,...(required.length?{required}:{}),additionalProperties:false};}
export function importOpenApi(document) {
  if (!/^3\./.test(document.openapi ?? '')) throw new Error('Expected OpenAPI 3.x JSON.');
  const output=[];
  for (const [path,rawItem] of Object.entries(document.paths??{})) {
    const item=resolve(rawItem,document);
    for (const method of ['get','post','put','patch','delete']) {
      const spec=item[method];if(!spec)continue;
      const server=spec.servers?.[0]??item.servers?.[0]??document.servers?.[0];
      let route=path;
      if (!route.startsWith('/admin/v2/store/')) {
        if(!server?.url)continue;
        const base=new URL(server.url);
        if(base.origin!=='https://api.easystore.co')continue;
        route=base.pathname.replace(/\/$/,'')+'/'+path.replace(/^\//,'');
      }
      if(!route.startsWith('/admin/v2/store/'))continue;
      if(!/^\/admin\/v2\/store\/[A-Za-z0-9_/{}/-]+$/.test(route))continue;
      const pathProps={},queryProps={},pathRequired=[],queryRequired=[],notes=[];
      const params=new Map();
      for(const parameter of [...(item.parameters??[]),...(spec.parameters??[])])params.set(`${parameter.in}:${parameter.name}`,parameter);
      for(const parameter of params.values()) {
        if(parameter.in==='path'){pathProps[parameter.name]=parameter.schema??{type:'string'};pathRequired.push(parameter.name);}
        if(parameter.in==='query'){
          if(/token|password|secret|api.?key|authorization/i.test(parameter.name)){notes.push('Sensitive query parameter omitted; authentication must be reviewed.');continue;}
          queryProps[parameter.name]=parameter.schema??{type:'string'};if(parameter.required)queryRequired.push(parameter.name);
        }
      }
      // Query defaults must remain valid; required query fields are caller supplied.
      let bodySchema=spec.requestBody?.content?.['application/json']?.schema;
      if(bodySchema?.type==='object')bodySchema={...bodySchema,additionalProperties:false};
      else if(spec.requestBody){bodySchema=undefined;notes.push('Unsupported body encoding/schema; implement a typed adapter.');}
      const hash=createHash('sha256').update(`${method} ${route}`).digest('hex').slice(0,16);
      output.push({id:`spec_${method}_${hash}`,method:method.toUpperCase(),path:route,description:'Imported admin operation. Review the internal spec and semantics before enabling.',enabled:false,source:'provided internal OpenAPI spec',...(pathRequired.length?{pathSchema:closedObject(pathProps,pathRequired)}:{}),...(Object.keys(queryProps).length?{querySchema:closedObject(queryProps,queryRequired)}:{}),...(bodySchema?{bodySchema}:{}),reviewNotes:notes});
    }
  }
  return output;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const[input,output='captures/operations.pending.json']=process.argv.slice(2);
  if(!input)throw new Error('Usage: npm run import:openapi -- internal-openapi.json [output.json]');
  const candidates=importOpenApi(JSON.parse(await readFile(input,'utf8')));
  await mkdir(dirname(output),{recursive:true});
  await writeFile(output,JSON.stringify(candidates,null,2)+'\n',{mode:0o600});
  console.log(`Wrote ${candidates.length} disabled operation candidates. Review schemas and unsupported features before enabling.`);
}

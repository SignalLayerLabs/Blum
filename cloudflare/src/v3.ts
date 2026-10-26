// V3 keeps financial authority in the authenticated origin, never in edge state.
const LIMIT = 25_000_000;
function responseHeaders(env: Env): Headers {
 return new Headers({'X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'SAMEORIGIN',
  'Permissions-Policy':'camera=(), microphone=(), geolocation=()', 'Cache-Control':'no-store',
  'X-BLUM-Source-Revision':env.SOURCE_REVISION,'X-BLUM-Worker-Version':env.CF_VERSION_METADATA.id});
}
function json(env: Env,value: unknown,status=200): Response {
 const headers=responseHeaders(env);headers.set('Content-Type','application/json');return new Response(JSON.stringify(value),{status,headers});
}
async function bodyWithinLimit(request: Request | Response,limit: number): Promise<ArrayBuffer> {
 const chunks:Uint8Array[]=[];let size=0;
 const reader=request.body?.getReader();
 if(reader)try {
  while(true){const next=await reader.read();if(next.done)break;size+=next.value.byteLength;
   if(size>limit)throw new Error('body_limit');chunks.push(next.value);}
 } finally {await reader.cancel().catch(()=>undefined);}
 const body=new Uint8Array(size);let offset=0;for(const chunk of chunks){body.set(chunk,offset);offset+=chunk.byteLength;}return body.buffer;
}
async function proxy(request: Request,env: Env): Promise<Response> {
 let origin:URL;
 try {origin=new URL(env.BACKEND_ORIGIN);if(origin.protocol!=='https:'||origin.username||origin.password||origin.pathname!=='/'||origin.search||origin.hash)throw Error('invalid');}
 catch{return json(env,{detail:'BACKEND_CONFIGURATION_INVALID'},503);}
 const url=new URL(request.url);const target=new URL(origin);target.pathname=url.pathname;target.search=url.search;
 const headers=new Headers({'Accept':'application/json'});let body:ArrayBuffer|undefined;
 if(url.pathname.startsWith('/api/v3/')) {
  const auth=request.headers.get('Authorization')??'';
  if(!/^Bearer [^\r\n]+$/.test(auth)||auth.length>4096)return json(env,{detail:'authentication_required'},401);
  headers.set('Authorization',auth);
  if(request.method==='POST') {
   const suppliedOrigin=request.headers.get('Origin');if(suppliedOrigin&&suppliedOrigin!==url.origin)return json(env,{detail:'cross_origin_command_denied'},403);
   if(!/^application\/json(?:\s*;|$)/i.test(request.headers.get('Content-Type')??''))return json(env,{detail:'json_body_required'},415);
   const key=request.headers.get('Idempotency-Key');if(!key||key.length>128)return json(env,{detail:'idempotency_key_required'},400);
   headers.set('Content-Type','application/json');headers.set('Idempotency-Key',key);
   try {body=await bodyWithinLimit(request,LIMIT);}catch{return json(env,{detail:'request_body_too_large'},413);}
  }
 }
 try {
  const upstream=await fetch(target,{method:request.method==='HEAD'?'GET':request.method,headers,body,redirect:'manual',signal:AbortSignal.timeout(30_000),cf:{cacheTtl:0,cacheEverything:false}});
  if(upstream.status>=300&&upstream.status<400){await upstream.body?.cancel();return json(env,{detail:'BACKEND_REDIRECT_REJECTED'},502);}
  const contentType=upstream.headers.get('Content-Type')??'';
  if(!/^application\/(?:[\w.-]+\+)?json\b/i.test(contentType)){await upstream.body?.cancel();return json(env,{detail:'BACKEND_NON_JSON_RESPONSE'},502);}
  const out=responseHeaders(env);out.set('Content-Type',contentType);out.set('X-BLUM-Backend',origin.hostname);
  if(request.method==='HEAD')await upstream.body?.cancel();
  return new Response(request.method==='HEAD'?null:upstream.body,{status:upstream.status,headers:out});
 }catch{return json(env,{detail:'BACKEND_UNAVAILABLE'},503);}
}
async function release(request: Request,env: Env): Promise<Response> {
 const url=new URL(request.url);url.pathname='/api/runtime/release';url.search='';
 const upstream=await proxy(new Request(url,{method:'GET'}),env);
 let value:Record<string,unknown>|null=null;
 try {value=JSON.parse(new TextDecoder().decode(await bodyWithinLimit(upstream,65536)));}catch{}
 const ready=upstream.ok&&value?.version==='3.0.0'&&value?.source_revision===env.SOURCE_REVISION
  && /^[0-9a-f]{64}$/.test(env.SOURCE_CONTENT_HASH)&&value?.source_content_hash===env.SOURCE_CONTENT_HASH
  && value?.api_ready===true&&value?.ui_ready===true&&value?.worker_ready===true&&value?.backend_ready===true;
 return json(env,{version:'3.0.0',source_revision:env.SOURCE_REVISION,source_content_hash:value?.source_content_hash??null,
  backend_source_revision:value?.source_revision??null,backend_ready:ready,worker_ready:value?.worker_ready===true,
  mode:'research_and_paper',broker_execution:false,worker_version:env.CF_VERSION_METADATA.id},ready?200:503);
}
export async function handleV3(request: Request,env: Env): Promise<Response> {
 const path=new URL(request.url).pathname;
 if(path==='/api/release'&&['GET','HEAD'].includes(request.method)){
  const result=await release(request,env);return request.method==='HEAD'?new Response(null,result):result;
 }
 const privateAPI=path.startsWith('/api/v3/');const publicAPI=['/health','/startup/status','/api/runtime/release'].includes(path);
 if(path.startsWith('/api/')&&!privateAPI&&!publicAPI)return json(env,{detail:'legacy_api_not_available'},410);
 if(privateAPI||publicAPI){
  if(!['GET','HEAD',...(privateAPI?['POST']:[])].includes(request.method))return json(env,{detail:'method_not_allowed'},405);
  return proxy(request,env);
 }
 if(!['GET','HEAD'].includes(request.method))return json(env,{detail:'method_not_allowed'},405);
 const asset=await env.ASSETS.fetch(request);const headers=new Headers(asset.headers);
 for(const [key,value] of responseHeaders(env))headers.set(key,value);
 if(headers.get('Content-Type')?.includes('text/html'))headers.set('Cache-Control','no-cache');
 return new Response(asset.body,{status:asset.status,headers});
}

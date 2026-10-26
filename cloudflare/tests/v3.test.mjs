import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.ts';

const env={RELEASE_CHANNEL:'v3',BACKEND_ORIGIN:'https://italianhype-blum.hf.space',SOURCE_REVISION:'a'.repeat(40),SOURCE_CONTENT_HASH:'c'.repeat(64),CF_VERSION_METADATA:{id:'v3'},ASSETS:{fetch:async()=>new Response('<html>Blum v3</html>',{headers:{'Content-Type':'text/html'}})}};
const auth={'Authorization':'Bearer private-operator','Content-Type':'application/json','Idempotency-Key':'stable-command'};

test('v3 anonymous mutations are denied before reaching the backend',async t=>{
 t.mock.method(globalThis,'fetch',()=>{throw Error('must not fetch');});
 const r=await worker.fetch(new Request('https://blum.example/api/v3/accounts',{method:'POST',body:'{}'}),env);
 assert.equal(r.status,401);
});
test('v3 forwards caller authentication, exact JSON and identity but strips cookies',async t=>{
 t.mock.method(globalThis,'fetch',async(url,options)=>{
  assert.equal(String(url),'https://italianhype-blum.hf.space/api/v3/accounts');
  assert.equal(options.method,'POST');assert.equal(options.headers.get('Authorization'),auth.Authorization);
  assert.equal(options.headers.get('Idempotency-Key'),'stable-command');assert.equal(options.headers.has('Cookie'),false);
  assert.equal(await new Response(options.body).text(),'{"cash":"10000"}');
  return new Response('{"id":"paper"}',{status:201,headers:{'Content-Type':'application/json','Set-Cookie':'private=1'}});
 });
 const r=await worker.fetch(new Request('https://blum.example/api/v3/accounts',{method:'POST',headers:{...auth,Cookie:'private=1'},body:'{"cash":"10000"}'}),env);
 assert.equal(r.status,201);assert.equal(r.headers.get('Cache-Control'),'no-store');assert.equal(r.headers.has('Set-Cookie'),false);
 assert.deepEqual(await r.json(),{id:'paper'});
});
test('v3 cross-origin writes and oversized bodies are rejected',async t=>{
 t.mock.method(globalThis,'fetch',()=>{throw Error('must not fetch');});
 const cross=await worker.fetch(new Request('https://blum.example/api/v3/accounts',{method:'POST',headers:{...auth,Origin:'https://foreign.example'},body:'{}'}),env);
 assert.equal(cross.status,403);
 const big=await worker.fetch(new Request('https://blum.example/api/v3/datasets',{method:'POST',headers:auth,body:'x'.repeat(25000001)}),env);
 assert.equal(big.status,413);
});
test('v3 release fails closed for stale content or a dead worker',async t=>{
 let state={version:'3.0.0',source_revision:'a'.repeat(40),source_content_hash:'c'.repeat(64),api_ready:true,ui_ready:true,worker_ready:true,backend_ready:true};
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify(state),{headers:{'Content-Type':'application/json'}}));
 assert.equal((await worker.fetch(new Request('https://blum.example/api/release'),env)).status,200);
 state={...state,worker_ready:false};assert.equal((await worker.fetch(new Request('https://blum.example/api/release'),env)).status,503);
 state={...state,worker_ready:true,source_content_hash:'d'.repeat(64)};assert.equal((await worker.fetch(new Request('https://blum.example/api/release'),env)).status,503);
});
test('v3 API redirects and HTML fallbacks never count as JSON success',async t=>{
 t.mock.method(globalThis,'fetch',async()=>new Response(null,{status:302,headers:{Location:'https://foreign.example'}}));
 const req=()=>new Request('https://blum.example/api/v3/overview',{headers:auth});
 assert.equal((await worker.fetch(req(),env)).status,502);
 t.mock.method(globalThis,'fetch',async()=>new Response('<html>old app</html>',{headers:{'Content-Type':'text/html'}}));
 assert.equal((await worker.fetch(req(),env)).status,502);
});
test('v3 assets identify the deployed revision and do not cache HTML',async()=>{
 const r=await worker.fetch(new Request('https://blum.example/'),env);
 assert.equal(await r.text(),'<html>Blum v3</html>');assert.equal(r.headers.get('X-BLUM-Source-Revision'),'a'.repeat(40));assert.equal(r.headers.get('Cache-Control'),'no-cache');
});
test('v3 legacy API routes remain unavailable even with an operator key',async t=>{
 t.mock.method(globalThis,'fetch',()=>{throw Error('must not fetch');});
 const r=await worker.fetch(new Request('https://blum.example/api/ascent/run',{method:'POST',headers:auth,body:'{}'}),env);
 assert.equal(r.status,410);
});

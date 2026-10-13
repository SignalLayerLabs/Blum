import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.ts';

const env = {
  BACKEND_ORIGIN: 'https://italianhype-blum.hf.space', SOURCE_REVISION: 'a'.repeat(40),
  CF_VERSION_METADATA: {id:'version'},
  ASSETS: {fetch: async () => new Response('<html>BLUM</html>', {headers:{'Content-Type':'text/html'}})}
};

test('static product pages use asset binding and release headers', async () => {
  const r = await worker.fetch(new Request('https://blum.example/evolution/'), env);
  assert.equal(await r.text(), '<html>BLUM</html>');
  assert.equal(r.headers.get('X-BLUM-Source-Revision'), 'a'.repeat(40));
  assert.equal(r.headers.get('X-Content-Type-Options'), 'nosniff');
});
test('asset HTML pages and JSON requests share a path without shadowing each other', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{"ticker":"AAPL"}', {headers:{'Content-Type':'application/json'}}));
  const api = await worker.fetch(new Request('https://blum.example/assets/AAPL', {headers:{Accept:'application/json'}}), env);
  assert.equal((await api.json()).ticker, 'AAPL');
  const page = await worker.fetch(new Request('https://blum.example/assets/AAPL/', {headers:{Accept:'text/html'}}), env);
  assert.equal(await page.text(), '<html>BLUM</html>');
});
test('public mutation never reaches backend', async t => {
  t.mock.method(globalThis, 'fetch', () => {throw Error('must not fetch');});
  const r = await worker.fetch(new Request('https://blum.example/api/ascent/run', {method:'POST'}), env);
  assert.equal(r.status, 405);
  assert.equal((await r.json()).detail, 'PUBLIC_OBSERVATORY_READ_ONLY');
});
test('API HTML fallback is rejected instead of reporting success', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>old deployment</html>', {headers:{'Content-Type':'text/html'}}));
  const r = await worker.fetch(new Request('https://blum.example/api/ascent/status'), env);
  assert.equal(r.status, 502);
  assert.equal((await r.json()).detail, 'BACKEND_NON_JSON_RESPONSE');
});
test('fresh JSON streams through with sanitized request and response headers', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(String(url), 'https://italianhype-blum.hf.space/api/brain/snapshot?limit=20');
    assert.equal(options.headers.has('Authorization'), false);
    assert.equal(options.headers.has('Cookie'), false);
    assert.equal(options.redirect, 'manual');
    return new Response('{"sample_size":42}', {headers:{'Content-Type':'application/json','Set-Cookie':'private=1','Cache-Control':'public,max-age=999'}});
  });
  const r = await worker.fetch(new Request('https://blum.example/api/brain/snapshot?limit=20', {headers:{Authorization:'secret',Cookie:'private'}}), env);
  assert.deepEqual(await r.json(), {sample_size:42});
  assert.equal(r.headers.has('Set-Cookie'), false);
  assert.equal(r.headers.get('Cache-Control'), 'no-store');
});
test('upstream redirects and network failures remain explicit', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(null, {status:302, headers:{Location:'https://elsewhere.example'}}));
  assert.equal((await worker.fetch(new Request('https://blum.example/health'), env)).status, 502);
  t.mock.method(globalThis, 'fetch', async () => {throw new Error('unavailable');});
  const r = await worker.fetch(new Request('https://blum.example/health'), env);
  assert.equal(r.status, 503);
  assert.equal((await r.json()).detail, 'BACKEND_UNAVAILABLE');
});
test('queries cannot request persistence, invalid origins fail closed', async () => {
  const r = await worker.fetch(new Request('https://blum.example/api/x?persist=true'), env);
  assert.equal(r.status, 400);
  const invalid = await worker.fetch(new Request('https://blum.example/health'), {...env,BACKEND_ORIGIN:'http://localhost:8080'});
  assert.equal(invalid.status, 503);
});
test('legacy snapshot paths proxy and release status is honest about backend readiness', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{"api_ready":false,"ui_ready":true}', {headers:{'Content-Type':'application/json'}}));
  const r = await worker.fetch(new Request('https://blum.example/api/release'), env);
  assert.equal(r.status, 503);
  const value = await r.json();
  assert.equal(value.backend_ready, false);
  assert.equal(value.source_revision, 'a'.repeat(40));
  const legacy = await worker.fetch(new Request('https://blum.example/system/status'), env);
  assert.equal(legacy.headers.get('Content-Type'), 'application/json');
});

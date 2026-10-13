// Cloudflare serves the product assets. Financial state remains in the Engine.
const LEGACY_API_ROOTS = new Set([
  'system', 'dashboard', 'performance', 'snapshots', 'learning', 'brain',
  'trader-brain', 'engine', 'runtime', 'analyst', 'architecture', 'model',
  'signals', 'assets', 'news', 'market', 'filings', 'sentiment', 'backtests',
  'accuracy', 'strategic', 'technical', 'portfolio', 'ipo'
]);

function isAPI(path: string): boolean {
  if (path === '/health' || path === '/startup/status' || path.startsWith('/api/')) return true;
  const parts = path.split('/').filter(Boolean);
  // /brain/ is a product page; /brain/status is a legacy API.
  return parts.length > 1 && LEGACY_API_ROOTS.has(parts[0]) && parts[0] !== 'assets';
}

function headers(env: Env): Headers {
  return new Headers({
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Frame-Options': 'SAMEORIGIN', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'X-BLUM-Source-Revision': env.SOURCE_REVISION,
    'X-BLUM-Worker-Version': env.CF_VERSION_METADATA.id
  });
}

function json(env: Env, value: unknown, status = 200): Response {
  const out = headers(env);
  out.set('Content-Type', 'application/json');
  out.set('Cache-Control', 'no-store');
  return new Response(JSON.stringify(value), {status, headers: out});
}

async function proxy(request: Request, env: Env, path?: string): Promise<Response> {
  const url = new URL(request.url);
  if ([...url.searchParams].some(([key, value]) => ['persist', 'refresh', 'rebuild', 'force'].includes(key.toLowerCase()) && ['true', '1'].includes(value.toLowerCase()))) {
    return json(env, {detail: 'MUTATING_QUERY_NOT_ALLOWED'}, 400);
  }
  let origin: URL;
  try {
    origin = new URL(env.BACKEND_ORIGIN);
    if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error('invalid origin');
  } catch {
    return json(env, {detail: 'BACKEND_CONFIGURATION_INVALID'}, 503);
  }
  const target = new URL(path ?? url.pathname + url.search, origin);
  try {
    const upstream = await fetch(target, {
      method: 'GET', headers: new Headers({'Accept': 'application/json'}),
      redirect: 'manual', signal: AbortSignal.timeout(12000),
      cf: {cacheTtl: 0, cacheEverything: false}
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      await upstream.body?.cancel();
      return json(env, {detail: 'BACKEND_REDIRECT_REJECTED'}, 502);
    }
    const contentType = upstream.headers.get('Content-Type') ?? '';
    if (!/^application\/(?:[\w.-]+\+)?json\b/i.test(contentType)) {
      await upstream.body?.cancel();
      return json(env, {detail: 'BACKEND_NON_JSON_RESPONSE', upstream_status: upstream.status}, 502);
    }
    const out = headers(env);
    out.set('Content-Type', contentType);
    out.set('Cache-Control', 'no-store');
    out.set('X-BLUM-Backend', origin.hostname);
    for (const name of ['Retry-After', 'X-BLUM-SLOW-ENDPOINT']) {
      const value = upstream.headers.get(name);
      if (value) out.set(name, value);
    }
    if (request.method === 'HEAD') await upstream.body?.cancel();
    return new Response(request.method === 'HEAD' ? null : upstream.body, {status: upstream.status, headers: out});
  } catch {
    return json(env, {detail: 'BACKEND_UNAVAILABLE'}, 503);
  }
}

async function releaseStatus(request: Request, env: Env): Promise<Response> {
  const result = await proxy(request, env, '/startup/status');
  let ready = false;
  if (result.ok && result.body) {
    const reader = result.body.getReader();
    let content = '', size = 0;
    const decoder = new TextDecoder();
    try {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        size += next.value.byteLength;
        if (size > 65536) throw new Error('oversized readiness payload');
        content += decoder.decode(next.value, {stream: true});
      }
      const state = JSON.parse(content + decoder.decode());
      ready = state.api_ready === true && state.ui_ready === true && !state.last_error;
    } catch { ready = false; } finally { await reader.cancel(); }
  }
  return json(env, {version: '2.2.0', source_revision: env.SOURCE_REVISION,
    worker_version: env.CF_VERSION_METADATA.id, backend_ready: ready,
    mode: 'paper_research_observatory', github: 'https://github.com/SignalLayerLabs/Blum'}, ready ? 200 : 503);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!['GET', 'HEAD'].includes(request.method)) {
      const response = json(env, {detail: 'PUBLIC_OBSERVATORY_READ_ONLY'}, 405);
      response.headers.set('Allow', 'GET, HEAD');
      return response;
    }
    const path = new URL(request.url).pathname;
    if (path === '/api/release') return releaseStatus(request, env);
    if (isAPI(path) || request.headers.get('Accept')?.includes('application/json')) return proxy(request, env);
    const asset = await env.ASSETS.fetch(request);
    const out = new Headers(asset.headers);
    for (const [key, value] of headers(env)) out.set(key, value);
    // A new release must not serve an old HTML document with new chunks.
    if (out.get('Content-Type')?.includes('text/html')) out.set('Cache-Control', 'no-cache');
    return new Response(asset.body, {status: asset.status, headers: out});
  }
} satisfies ExportedHandler<Env>;

import publicRoutes from '../../backend/app/data/public_api_routes.json' with {type: 'json'};
// Cloudflare serves the product assets. Financial state remains in the Engine.
const PUBLIC_PATHS = publicRoutes.map(template => new RegExp('^' + template.replace(/\{[^}]+\}/g, '[^/]+') + '$'));
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
  if ([...url.searchParams].some(([key, value]) => ['persist', 'refresh', 'rebuild', 'force'].includes(key.toLowerCase()) && !['false', '0'].includes(value.trim().toLowerCase()))) {
    return json(env, {detail: 'MUTATING_QUERY_NOT_ALLOWED'}, 400);
  }
  if (!PUBLIC_PATHS.some(pattern => pattern.test(path ?? url.pathname))) {
    return json(env, {detail: 'PUBLIC_API_ROUTE_NOT_AVAILABLE'}, 404);
  }
  let origin: URL;
  try {
    origin = new URL(env.BACKEND_ORIGIN);
    if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error('invalid origin');
  } catch {
    return json(env, {detail: 'BACKEND_CONFIGURATION_INVALID'}, 503);
  }
  const target = new URL(origin);
  target.pathname = path ?? url.pathname;
  target.search = path ? '' : url.search;
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

async function boundedJSON(result: Response): Promise<Record<string, unknown> | null> {
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
      const value: unknown = JSON.parse(content + decoder.decode());
      return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
    } catch { return null; } finally { await reader.cancel().catch(() => undefined); }
  }
  await result.body?.cancel().catch(() => undefined);
  return null;
}

async function releaseStatus(request: Request, env: Env): Promise<Response> {
  const probe = new Request(request, {method:'GET'});
  const [startup, release] = await Promise.all([
    proxy(probe, env, '/startup/status').then(boundedJSON),
    proxy(probe, env, '/api/runtime/release').then(boundedJSON)
  ]);
  const ready = startup?.api_ready === true && startup?.ui_ready === true && !startup?.last_error
    && release?.source_revision === env.SOURCE_REVISION && release?.version === '2.3.0'
    && /^[0-9a-f]{64}$/.test(env.SOURCE_CONTENT_HASH) && release?.source_content_hash === env.SOURCE_CONTENT_HASH;
  return json(env, {version: '2.3.0', source_revision: env.SOURCE_REVISION,
    source_content_hash: release?.source_content_hash ?? null,
    worker_version: env.CF_VERSION_METADATA.id, backend_ready: ready,
    backend_source_revision:release?.source_revision ?? null,
    backend_version:release?.version ?? null,
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
    if (path === '/api/release') {
      const response = await releaseStatus(request, env);
      return request.method === 'HEAD' ? new Response(null, response) : response;
    }
    if (isAPI(path) || request.headers.get('Accept')?.includes('application/json')) return proxy(request, env);
    const asset = await env.ASSETS.fetch(request);
    const out = new Headers(asset.headers);
    for (const [key, value] of headers(env)) out.set(key, value);
    // A new release must not serve an old HTML document with new chunks.
    if (out.get('Content-Type')?.includes('text/html')) out.set('Cache-Control', 'no-cache');
    return new Response(asset.body, {status: asset.status, headers: out});
  }
} satisfies ExportedHandler<Env>;

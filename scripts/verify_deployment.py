"""Verify source revision, JSON APIs, readiness and public read-only boundary."""
import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backend-only', action='store_true')
parser.add_argument('--timeout', type=int, default=120)
args = parser.parse_args()
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
backend = 'https://italianhype-blum.hf.space'
site = 'https://blum.signallayerlabs.workers.dev'
verification_headers = {
    'User-Agent': 'BLUM-Deployment-Verification/2.2.0 (+https://github.com/SignalLayerLabs/Blum)',
}

def request(url, **kwargs):
    # Identify the maintained verifier explicitly; workers.dev rejects Python's default agent.
    return urllib.request.Request(url, headers=verification_headers, **kwargs)

def get_json(origin, path):
    response = urllib.request.urlopen(request(origin+path), timeout=15)
    if 'application/json' not in response.headers.get('Content-Type', ''):
        raise ValueError('Expected a JSON API response: '+path)
    return json.load(response)

deadline = time.monotonic() + args.timeout
last_error = ''
while time.monotonic() < deadline:
    try:
        startup = get_json(backend, '/startup/status')
        deployed = get_json(backend, '/api/runtime/release')
        if not startup.get('api_ready') or not startup.get('ui_ready') or startup.get('last_error'):
            raise ValueError('Backend is restoring or unavailable.')
        if deployed.get('source_revision') != revision or deployed.get('version') != '2.2.0':
            raise ValueError('Backend revision has not finished deploying.')
        break
    except (OSError, ValueError) as exc:
        last_error = str(exc)
        time.sleep(10)
else:
    raise SystemExit('Backend verification failed: '+last_error)
print('Backend ready at', revision, flush=True)
if not args.backend_only:
    public = get_json(site, '/api/release')
    if public.get('source_revision') != revision or not public.get('backend_ready'):
        raise SystemExit('Cloudflare revision or backend readiness mismatch.')
    for path in ['/api/brain/snapshot', '/api/training/snapshot', '/api/paper-trading/snapshot?limit=1',
                 '/api/alpha/snapshot', '/api/ascent/status']:
        payload = get_json(site, path)
        if not isinstance(payload, dict): raise SystemExit('Invalid snapshot: '+path)
        print('Verified JSON snapshot', path, flush=True)
    try:
        urllib.request.urlopen(request(site+'/api/ascent/run', data=b'{}', method='POST'), timeout=15)
        raise SystemExit('Public research mutation was unexpectedly allowed.')
    except urllib.error.HTTPError as exc:
        if exc.code != 405: raise
    for path in ['/brain/', '/training-ground/', '/paper-trading/', '/alpha/', '/evolution/']:
        response = urllib.request.urlopen(request(site+path), timeout=15)
        if response.status != 200 or 'text/html' not in response.headers.get('Content-Type', ''):
            raise SystemExit('Product page unavailable: '+path)
    print('Cloudflare pages, live API snapshots and write protection verified.', flush=True)

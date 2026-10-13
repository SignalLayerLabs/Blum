"""Fail closed unless HEAD is current main and all release CI jobs passed."""
import json
import os
import subprocess
import urllib.request

repo = os.environ.get('GITHUB_REPOSITORY', 'SignalLayerLabs/Blum')
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()

def api(path):
    request = urllib.request.Request(f'https://api.github.com/repos/{repo}/{path}',
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'], 'Accept':'application/vnd.github+json'})
    return json.load(urllib.request.urlopen(request, timeout=30))

if api('commits/main')['sha'] != revision:
    raise SystemExit('Refusing to deploy a revision that is not current canonical main.')
runs = api(f'actions/runs?head_sha={revision}&status=completed&per_page=50')['workflow_runs']
verified = [run for run in runs if run['name'] == 'Verify BLUM' and run['conclusion'] == 'success']
if not verified:
    raise SystemExit('No successful Verify BLUM run exists for this exact main revision.')
jobs = api(f"actions/runs/{verified[0]['id']}/jobs?per_page=100")['jobs']
passed = {job['name'] for job in jobs if job['conclusion'] == 'success'}
if not {'backend', 'frontend', 'gateway'}.issubset(passed):
    raise SystemExit('Required backend, frontend and gateway jobs have not all passed.')
print('Verified canonical release', revision)

"""Fail closed unless HEAD is current main and both exact-revision CI suites pass."""
import json
import os
import subprocess
import time
import urllib.request

REQUIRED={'Verify BLUM':{'backend','frontend','gateway'},'Verify Blum v3':{'financial-contracts','web'}}


def workflows_verified(runs,fetch_jobs):
    for name,required in REQUIRED.items():
        matches=[run for run in runs if run['name']==name]
        if not matches:return False
        latest=max(matches,key=lambda run:run['id'])
        if latest.get('conclusion')!='success':return False
        passed={job['name'] for job in fetch_jobs(latest['id']) if job['conclusion']=='success'}
        if not required.issubset(passed):return False
    return True


def main():
    repo=os.environ.get('GITHUB_REPOSITORY','SignalLayerLabs/Blum')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    def api(path):
        request=urllib.request.Request(f'https://api.github.com/repos/{repo}/{path}',headers={
            'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
        return json.load(urllib.request.urlopen(request,timeout=30))
    deadline=time.monotonic()+1200
    while time.monotonic()<deadline:
        if api('commits/main')['sha']!=revision:raise SystemExit('Refusing stale canonical main revision.')
        runs=api(f'actions/runs?head_sha={revision}&per_page=50')['workflow_runs']
        if workflows_verified(runs,lambda run:api(f'actions/runs/{run}/jobs?per_page=100')['jobs']):
            print('Verified both canonical CI suites',revision);return
        if any(r['name'] in REQUIRED and r.get('conclusion') in {'failure','cancelled','timed_out'} for r in runs):
            raise SystemExit('A required exact-revision verification workflow failed.')
        print('Waiting for both exact-revision CI suites.',flush=True);time.sleep(10)
    raise SystemExit('Both required verification suites did not pass within the release window.')


if __name__=='__main__':main()

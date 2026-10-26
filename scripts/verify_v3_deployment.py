"""Verify the actual v3 origin and edge without creating financial commands."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from blum_v3.release import release_identity

BACKEND='https://italianhype-blum.hf.space'
SITE='https://blum.signallayerlabs.workers.dev'
HEADERS={'User-Agent':'BLUM-Deployment-Verification/3.0.0 (+https://github.com/SignalLayerLabs/Blum)'}


def verify_payload(value,revision,content_hash):
    required=dict(version='3.0.0',source_revision=revision,source_content_hash=content_hash,backend_ready=True,worker_ready=True,broker_execution=False)
    if any(value.get(key)!=expected for key,expected in required.items()):raise ValueError('V3 revision, protected content or API/worker readiness mismatch.')


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,response,code,message,headers,new_url):
        return None


def fetch(origin,path,**kwargs):
    return urllib.request.build_opener(RejectRedirects()).open(urllib.request.Request(origin+path,headers=HEADERS,**kwargs),timeout=20)


def get_json(origin,path):
    with fetch(origin,path) as response:
        if 'application/json' not in response.headers.get('Content-Type',''):raise ValueError('Expected JSON from '+path)
        return json.load(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend-only',action='store_true');parser.add_argument('--timeout',type=int,default=120)
    args=parser.parse_args();revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    content_hash=release_identity()['source_content_hash'];deadline=time.monotonic()+args.timeout;last_error=''
    while time.monotonic()<deadline:
        try:
            verify_payload(get_json(BACKEND,'/api/runtime/release'),revision,content_hash)
            if not args.backend_only:verify_payload(get_json(SITE,'/api/release'),revision,content_hash)
            break
        except (OSError,ValueError) as error:last_error=str(error);time.sleep(10)
    else:raise SystemExit('V3 release verification failed: '+last_error)
    print('Verified v3 origin revision, code, PostgreSQL and worker readiness:',revision,flush=True)
    if args.backend_only:return
    with fetch(SITE,'/') as response:
        html=response.read().decode()
        if response.status!=200 or 'Connect your workspace.' not in html or response.headers.get('X-BLUM-Source-Revision')!=revision:
            raise SystemExit('V3 public workspace HTML or source header mismatch.')
    for path,kwargs in [('/api/v3/overview',{}),('/api/v3/accounts',dict(method='POST',data=b'{}'))]:
        try:fetch(SITE,path,**kwargs);raise SystemExit('Anonymous private access was unexpectedly allowed.')
        except urllib.error.HTTPError as error:
            if error.code!=401:raise
    print('Verified public v3 workspace and authenticated read/command boundary; no financial commands created.',flush=True)


if __name__=='__main__':main()

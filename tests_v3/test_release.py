"""Production readiness must reflect actual code, database, assets and worker."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_release_identity_uses_baked_revision_and_protected_content(tmp_path,monkeypatch):
    from blum_v3.release import release_identity
    package=tmp_path/'blum_v3';package.mkdir();(package/'api.py').write_text('first')
    (package/'build_revision.json').write_text(json.dumps({'source_revision':'a'*40}))
    monkeypatch.setenv('BLUM_SOURCE_REVISION','b'*40)
    first=release_identity(tmp_path)
    assert first['source_revision']=='a'*40 and len(first['source_content_hash'])==64
    (package/'api.py').write_text('changed')
    assert release_identity(tmp_path)['source_content_hash']!=first['source_content_hash']
    (package/'build_revision.json').write_text('{"source_revision":"invalid"}')
    assert release_identity(tmp_path)['source_revision']=='unavailable'


def test_readiness_requires_database_assets_and_running_worker(tmp_path):
    from blum_v3.release import readiness
    from blum_v3.storage import Repository
    repo=Repository('sqlite:///:memory:');(tmp_path/'index.html').write_text('Blum')
    ready=readiness(repo,tmp_path,str(os.getpid()))
    assert ready['api_ready'] and ready['ui_ready'] and ready['worker_ready']
    assert not readiness(repo,tmp_path,None)['worker_ready']
    assert not readiness(repo,tmp_path,'not-a-pid')['worker_ready']
    (tmp_path/'index.html').unlink()
    assert not readiness(repo,tmp_path,str(os.getpid()))['ui_ready']


def test_runtime_reuses_private_key_and_postgres_without_legacy_writers():
    from blum_v3.runtime import runtime_configuration
    env=runtime_configuration({'DATABASE_URL':'postgresql+psycopg2://user:private@localhost/blum','BLUM_ASCENT_ADMIN_KEY':'existing-private-key'})
    assert env['BLUM_OPERATOR_TOKEN']=='existing-private-key'
    assert env['BLUM_DATABASE_URL']=='postgresql+psycopg://user:private@localhost/blum'
    assert env['BLUM_ENV']=='production'
    with pytest.raises(ValueError,match='operator_key_required'):
        runtime_configuration({'DATABASE_URL':'postgresql://localhost/blum'})
    with pytest.raises(ValueError,match='production_requires_postgresql'):
        runtime_configuration({'BLUM_DATABASE_URL':'sqlite:///:memory:','BLUM_OPERATOR_TOKEN':'key'})


def test_supervisor_stops_peer_if_a_required_process_exits():
    from blum_v3.runtime import supervise
    children=[]
    def spawn(command,**kwargs):
        child=subprocess.Popen(command,**kwargs);children.append(child);return child
    result=supervise([[sys.executable,'-c','import time; time.sleep(.05)'],[sys.executable,'-c','import time; time.sleep(20)']],dict(os.environ),spawn=spawn)
    assert result!=0 and len(children)==2 and all(p.poll() is not None for p in children)


def test_deployment_gate_requires_both_latest_workflows_and_all_jobs():
    from scripts.check_release_revision import workflows_verified
    runs=[dict(id=1,name='Verify BLUM',conclusion='success'),dict(id=2,name='Verify Blum v3',conclusion='success')]
    jobs={1:[dict(name=n,conclusion='success') for n in ['backend','frontend','gateway']],2:[dict(name=n,conclusion='success') for n in ['financial-contracts','web']]}
    assert workflows_verified(runs,lambda run:jobs[run])
    assert not workflows_verified(runs[:1],lambda run:jobs[run])
    jobs[2][0]['conclusion']='failure'
    assert not workflows_verified(runs,lambda run:jobs[run])
    jobs[2][0]['conclusion']='success'
    assert not workflows_verified(runs+[dict(id=3,name='Verify Blum v3',conclusion=None)],lambda run:jobs[run])


def test_public_verifier_rejects_stale_revision_content_and_dead_worker():
    from scripts.verify_v3_deployment import verify_payload
    value=dict(version='3.0.0',source_revision='a'*40,source_content_hash='c'*64,backend_ready=True,worker_ready=True,broker_execution=False)
    verify_payload(value,'a'*40,'c'*64)
    for field,bad in [('source_revision','b'*40),('source_content_hash','d'*64),('worker_ready',False),('backend_ready',False),('broker_execution',True)]:
        with pytest.raises(ValueError):verify_payload(value|{field:bad},'a'*40,'c'*64)


def test_deployment_http_policy_rejects_redirect_before_second_request():
    import io
    import urllib.error
    import urllib.request
    from email.message import Message
    from urllib.response import addinfourl
    from scripts.verify_v3_deployment import RejectRedirects
    calls=[]
    class OriginFixture(urllib.request.HTTPHandler):
        def http_open(self,request):
            calls.append(request.full_url)
            headers=Message();headers['Location']='http://origin.invalid/redirected';headers['Content-Type']='application/json'
            response=addinfourl(io.BytesIO(b'{}'),headers,request.full_url,302 if len(calls)==1 else 200)
            response.msg='fixture';return response
    opener=urllib.request.build_opener(OriginFixture(),RejectRedirects())
    with pytest.raises(urllib.error.HTTPError) as error:opener.open('http://origin.invalid/api/runtime/release')
    assert error.value.code==302 and len(calls)==1

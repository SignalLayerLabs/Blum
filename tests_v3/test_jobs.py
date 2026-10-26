from datetime import datetime, timezone, timedelta

import pytest


def test_job_leases_recover_once_and_stale_worker_cannot_complete(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.jobs import JobService
    clock=[datetime(2024,1,1,tzinfo=timezone.utc)]
    jobs=JobService(Repository('sqlite:///'+str(tmp_path/'j.db')),clock=lambda:clock[0])
    queued=jobs.enqueue('research',{'experiment_id':'unit'},key='job')
    assert jobs.enqueue('research',{'experiment_id':'unit'},key='job')['id']==queued['id']
    first=jobs.claim('worker-one',lease_seconds=10)
    assert first['attempt']==1
    assert jobs.claim('worker-two') is None
    clock[0]+=timedelta(seconds=11)
    second=jobs.claim('worker-two')
    assert second['attempt']==2
    with pytest.raises(ValueError,match='lease_lost'):
        jobs.finish(first['id'],first['lease_token'],{'bad':'old'})
    jobs.finish(second['id'],second['lease_token'],{'result':'accepted'})
    assert jobs.get(queued['id'])['status']=='SUCCEEDED'
    assert jobs.claim('worker-three') is None


def test_cancel_job_and_idempotency_conflict(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.jobs import JobService
    jobs=JobService(Repository('sqlite:///'+str(tmp_path/'j.db')))
    job=jobs.enqueue('paper_step',{'account_id':'one'},key='one')
    with pytest.raises(ValueError,match='idempotency_conflict'):
        jobs.enqueue('paper_step',{'account_id':'two'},key='one')
    jobs.cancel(job['id'])
    assert jobs.claim('worker') is None


def test_unknown_job_type_is_not_executable(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.jobs import JobService
    with pytest.raises(ValueError,match='unknown_job_type'):
        JobService(Repository('sqlite:///'+str(tmp_path/'j.db'))).enqueue('python',{'cmd':'arbitrary'},key='unsafe')

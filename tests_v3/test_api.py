from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select,func
import asyncio

from test_execution import dataset

AUTH={'Authorization':'Bearer unit-secret'}


def socket_free_loop():
    """Keep in-memory ASGI tests progressing where sandbox self-pipe sends are denied."""
    loop=asyncio.new_event_loop()
    def tick(): loop.call_later(0.01,tick)
    loop.call_soon(tick)
    return loop


def setup(tmp_path):
    from blum_v3.api import create_app
    from blum_v3.storage import Repository
    source=dataset(length=40)
    repo=Repository('sqlite:///'+str(tmp_path/'api.db'));repo.save_dataset(source)
    clock=lambda:source.provenance.first_seen_at+timedelta(minutes=1)
    client=TestClient(create_app(repository=repo,token='unit-secret',clock=clock),backend_options={'loop_factory':socket_free_loop})
    return client,repo,source


def test_private_data_and_mutations_require_credentials(tmp_path):
    client,repo,source=setup(tmp_path)
    assert client.get('/api/v3/datasets').status_code==401
    assert client.get('/api/v3/datasets',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert client.get('/health').status_code==200
    assert client.post('/api/v3/accounts',json={}).status_code==401
    assert 'unit-secret' not in client.get('/health').text


def test_import_provenance_datasets_and_validation_errors(tmp_path):
    client,repo,source=setup(tmp_path)
    payload={'instrument':source.instrument.model_dump(mode='json'),'provenance':source.provenance.model_dump(mode='json'),
        'rows':[bar.model_dump(mode='json') for bar in source.bars]}
    imported=client.post('/api/v3/datasets',json=payload,headers=AUTH)
    assert imported.status_code==201
    assert imported.json()['accepted']==40
    assert client.get('/api/v3/datasets',headers=AUTH).json()[0]['provider']=='unit-contract'
    invalid=client.post('/api/v3/datasets',json=payload|{'unexpected':'field'},headers=AUTH)
    assert invalid.status_code==422


def test_research_job_executes_and_gets_never_start_work(tmp_path):
    from blum_v3.jobs import JobService
    from blum_v3.worker import Worker
    from blum_v3.storage import jobs,events
    client,repo,source=setup(tmp_path)
    created=client.post('/api/v3/experiments',json={'dataset_id':source.dataset_id,'config':{'lookback':3},'family_id':'api-family','hypothesis':'Unit contract test'},headers=AUTH|{'Idempotency-Key':'trial'})
    assert created.status_code==202,created.text
    job=created.json()['job']
    assert Worker(repo).run_once() is True
    assert client.get('/api/v3/jobs/'+job['id'],headers=AUTH).json()['status']=='SUCCEEDED'
    report=client.get('/api/v3/experiments/'+created.json()['experiment']['id'],headers=AUTH).json()
    assert report['report']['scope'].startswith('Historical')
    assert report['holdout']['opened'] is False
    with repo.engine.connect() as conn: before=(conn.scalar(select(func.count()).select_from(jobs)),conn.scalar(select(func.count()).select_from(events)))
    for _ in range(2):
        assert client.get('/api/v3/overview',headers=AUTH).status_code==200
        assert client.get('/api/v3/operations',headers=AUTH).status_code==200
    with repo.engine.connect() as conn: after=(conn.scalar(select(func.count()).select_from(jobs)),conn.scalar(select(func.count()).select_from(events)))
    assert before==after


def test_paper_orders_use_actual_dataset_reference_and_remain_unfilled_without_new_data(tmp_path):
    client,repo,source=setup(tmp_path)
    account=client.post('/api/v3/accounts',json={'name':'Unit paper account','market':'equity','currency':'USD','cash':'10000'},headers=AUTH|{'Idempotency-Key':'account'}).json()
    submitted=client.post('/api/v3/accounts/'+account['id']+'/orders',json={'dataset_id':source.dataset_id,'side':'BUY','quantity':'5'},headers=AUTH|{'Idempotency-Key':'order'})
    assert submitted.status_code==201,submitted.text
    assert submitted.json()['source_ref']==source.dataset_id
    from blum_v3.paper import PaperService
    result=PaperService(repo).step(account['id'],source.dataset_id)
    assert result['fills']==0
    assert client.get('/api/v3/accounts/'+account['id'],headers=AUTH).json()['cash']=='10000'


def test_missing_idempotency_key_and_raw_exception_details_are_not_exposed(tmp_path):
    client,repo,source=setup(tmp_path)
    response=client.post('/api/v3/accounts',json={'name':'Unit','market':'equity','currency':'USD','cash':'10000'},headers=AUTH)
    assert response.status_code==422
    missing=client.get('/api/v3/accounts/not-found',headers=AUTH)
    assert missing.status_code==404
    assert 'Traceback' not in missing.text


def test_oversized_stream_is_rejected_before_financial_mutation(tmp_path):
    from blum_v3.security import RequestBodyLimit
    client,repo,source=setup(tmp_path)
    bounded=TestClient(RequestBodyLimit(client.app,limit=128),backend_options={'loop_factory':socket_free_loop})
    result=bounded.post('/api/v3/accounts',content=b'x'*256,headers=AUTH|{'Content-Type':'application/json'})
    assert result.status_code==413
    assert client.get('/api/v3/accounts',headers=AUTH).json()==[]


def test_non_ascii_authentication_header_is_denied_without_server_error(tmp_path):
    client,repo,source=setup(tmp_path)
    result=client.get('/api/v3/accounts',headers={b'Authorization':b'Bearer \xff'})
    assert result.status_code==401

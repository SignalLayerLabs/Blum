"""Optional real PostgreSQL checks; CI supplies an isolated test database."""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from urllib.parse import quote

import pytest

pytestmark=pytest.mark.skipif(not os.environ.get('BLUM_TEST_POSTGRES_URL'),reason='Dedicated PostgreSQL test database not configured')


@pytest.fixture
def postgres_repository():
    import psycopg
    from psycopg import sql
    from blum_v3.storage import Repository
    raw=os.environ['BLUM_TEST_POSTGRES_URL'].replace('postgresql+psycopg://','postgresql://')
    schemas=[];repositories=[]
    def create():
        name='blum_test_'+uuid4().hex
        with psycopg.connect(raw,autocommit=True) as conn:conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        schemas.append(name)
        url=raw+('&' if '?' in raw else '?')+'options='+quote('-csearch_path='+name,safe='')
        repo=Repository(url,production=True);repositories.append(repo)
        return repo
    yield create
    for repo in repositories:repo.engine.dispose()
    with psycopg.connect(raw,autocommit=True) as conn:
        for name in schemas:conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))


def test_postgres_serializes_competing_account_writers(postgres_repository):
    from blum_v3.portfolio import PortfolioService
    from blum_v3.domain import Instrument,now
    from blum_v3.storage import Repository
    repo=postgres_repository();svc=PortfolioService(repo);at=now()
    independent=Repository(repo.engine.url.render_as_string(hide_password=False),production=True)
    other=PortfolioService(independent)
    account=svc.open_account(name='Concurrent account',market='equity',currency='USD',cash='10000',key='epoch')['id']
    instrument=Instrument(symbol='SPY',market='equity',quote_currency='USD')
    def submit(key):
        writer=svc if key=='one' else other
        try:writer.submit_order(account,instrument=instrument,side='BUY',quantity='15',reference_price='100',decision_at=now(),reference_at=at,source_ref='unit',key=key);return 'accepted'
        except ValueError:return 'denied'
    with ThreadPoolExecutor(2) as workers:results=list(workers.map(submit,['one','two']))
    assert sorted(results)==['accepted','denied']
    assert D(svc.snapshot(account)['reserved_cash'])==D('1530')
    independent.engine.dispose()


def test_postgres_archive_restores_consistent_projection(postgres_repository,tmp_path):
    from blum_v3.portfolio import PortfolioService
    from blum_v3.archive import export_archive,restore_archive
    source=postgres_repository();target=postgres_repository()
    account=PortfolioService(source).open_account(name='Archive source',market='forex',currency='EUR',cash='10000',key='epoch')
    path=tmp_path/'postgres.json';export_archive(source,path);restore_archive(target,path)
    assert PortfolioService(target).snapshot(account['id'])['cash']=='10000'

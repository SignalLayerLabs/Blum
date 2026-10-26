import json
from decimal import Decimal as D
import pytest


def test_archive_restore_preserves_cash_and_detects_modified_content(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.portfolio import PortfolioService
    from blum_v3.archive import export_archive,restore_archive
    source=Repository('sqlite:///'+str(tmp_path/'source.db'))
    account=PortfolioService(source).open_account(name='Archive contract',market='equity',currency='USD',cash='10000',key='epoch')
    path=tmp_path/'backup.json'
    receipt=export_archive(source,path)
    target=Repository('sqlite:///'+str(tmp_path/'target.db'))
    restore_archive(target,path)
    assert D(PortfolioService(target).snapshot(account['id'])['cash'])==D('10000')
    assert receipt['accounts']==1
    content=json.loads(path.read_text());content['tables']['v3_accounts'][0]['payload']='{}';path.write_text(json.dumps(content))
    with pytest.raises(ValueError,match='archive_integrity'):
        restore_archive(Repository('sqlite:///'+str(tmp_path/'bad.db')),path)


def test_archive_cannot_overwrite_or_restore_into_nonempty_state(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.portfolio import PortfolioService
    from blum_v3.archive import export_archive,restore_archive
    source=Repository('sqlite:///'+str(tmp_path/'source.db'))
    PortfolioService(source).open_account(name='Existing',market='forex',currency='USD',cash='100',key='epoch')
    path=tmp_path/'backup.json';export_archive(source,path)
    with pytest.raises(FileExistsError):export_archive(source,path)
    with pytest.raises(ValueError,match='restore_requires_empty_database'):restore_archive(source,path)


def test_production_refuses_sqlite_and_legacy_import_has_no_financial_authority(tmp_path):
    from blum_v3.storage import Repository
    from blum_v3.archive import import_legacy_evidence
    from blum_v3.portfolio import PortfolioService
    with pytest.raises(ValueError,match='production_requires_postgresql'):
        Repository('sqlite:///:memory:',production=True)
    repo=Repository('sqlite:///'+str(tmp_path/'r.db'))
    path=tmp_path/'legacy.json';path.write_text(json.dumps({'records':[{'legacy_id':1,'reported_return':'500%'}]}))
    result=import_legacy_evidence(repo,path)
    assert result['authority']=='LEGACY_READ_ONLY'
    assert PortfolioService(repo).list_accounts()==[]

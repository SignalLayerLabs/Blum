"""Private, integrity-checked logical archives and isolated legacy evidence."""
from collections import defaultdict
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile

from sqlalchemy import select,insert,func

from .domain import encode,identity,now,decimal
from .storage import metadata,accounts,events,legacy_evidence

TABLES={name:table for name,table in metadata.tables.items() if name!='v3_schema'}


def export_archive(repository,destination) -> dict:
    path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError(path)
    with repository.lock,repository.engine.connect() as conn:
        if repository.engine.dialect.name=='postgresql':conn=conn.execution_options(isolation_level='REPEATABLE READ')
        with conn.begin():
            tables={name:[dict(row) for row in conn.execute(select(table)).mappings()] for name,table in TABLES.items()}
    content=dict(schema_version=1,application='blum-v3',exported_at=now().isoformat(),tables=tables)
    content['digest']=identity(content)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False,encoding='utf-8') as stream:
        temporary=Path(stream.name);os.chmod(temporary,0o600);stream.write(encode(content));stream.flush();os.fsync(stream.fileno())
    try:os.link(temporary,path) # Atomic publication that refuses to replace an existing archive.
    finally:temporary.unlink(missing_ok=True)
    return dict(digest=content['digest'],accounts=len(tables['v3_accounts']),events=len(tables['v3_events']),path=str(path))


def _verify_journal(tables):
    grouped=defaultdict(list)
    for row in tables['v3_events']:grouped[row['account_id']].append(row)
    for account in tables['v3_accounts']:
        state=json.loads(account['payload']);previous='';cash=Decimal(0);sequence=0
        for row in sorted(grouped[account['id']],key=lambda r:r['sequence']):
            event=json.loads(row['payload']);digest=event.pop('id')
            if identity(event)!=digest or event['previous']!=previous or event['sequence']!=sequence+1:raise ValueError('archive_journal_integrity')
            by_currency=defaultdict(Decimal)
            for posting in event['postings']:
                by_currency[posting['currency']]+=decimal(posting['amount'])
                if posting['book']=='cash' and posting['currency']==state['currency']:cash+=decimal(posting['amount'])
            if any(amount!=0 for amount in by_currency.values()):raise ValueError('archive_unbalanced_journal')
            previous=digest;sequence=event['sequence']
        if previous!=state['last_event'] or sequence!=state['version'] or cash!=decimal(state['cash']):raise ValueError('archive_projection_reconciliation')


def restore_archive(repository,source):
    value=json.loads(Path(source).read_text());digest=value.pop('digest',None)
    if value.get('schema_version')!=1 or value.get('application')!='blum-v3' or identity(value)!=digest or set(value.get('tables',{}))!=set(TABLES):
        raise ValueError('archive_integrity_failure')
    _verify_journal(value['tables'])
    with repository.transaction() as conn:
        if any(conn.scalar(select(func.count()).select_from(table)) for table in TABLES.values()):raise ValueError('restore_requires_empty_database')
        for name,rows in value['tables'].items():
            if rows:conn.execute(insert(TABLES[name]),rows)
    return dict(digest=digest,accounts=len(value['tables']['v3_accounts']),status='RESTORED_AND_RECONCILED')


def import_legacy_evidence(repository,source):
    raw=Path(source).read_text();value=json.loads(raw)
    digest=identity(value);payload=encode(dict(source_hash=digest,imported_at=now(),authority='LEGACY_READ_ONLY',content=value))
    with repository.transaction() as conn:
        if conn.scalar(select(legacy_evidence.c.id).where(legacy_evidence.c.id==digest)) is None:
            conn.execute(insert(legacy_evidence).values(id=digest,payload=payload))
    return dict(source_hash=digest,authority='LEGACY_READ_ONLY',financial_accounts_created=0)

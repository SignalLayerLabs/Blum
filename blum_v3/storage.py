"""Versioned relational storage, immutable artifacts and serialized financial writes."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
from threading import RLock

from sqlalchemy import (Column, Integer, MetaData, String, Table, Text, UniqueConstraint,
                        create_engine, select, insert, update)
from sqlalchemy.pool import StaticPool

from .domain import AcceptedDataset, encode, identity, now

metadata = MetaData()
schema = Table('v3_schema', metadata, Column('version', Integer, primary_key=True))
datasets = Table('v3_datasets', metadata, Column('id', String(64), primary_key=True), Column('payload', Text, nullable=False))
accounts = Table('v3_accounts', metadata, Column('id', String(64), primary_key=True), Column('payload', Text, nullable=False), Column('version', Integer, nullable=False))
events = Table('v3_events', metadata, Column('id', String(64), primary_key=True), Column('account_id', String(64), nullable=False), Column('sequence', Integer, nullable=False), Column('payload', Text, nullable=False), UniqueConstraint('account_id', 'sequence'))
commands = Table('v3_commands', metadata, Column('scope', String(100), primary_key=True), Column('key', String(128), primary_key=True), Column('fingerprint', String(64), nullable=False), Column('result', Text, nullable=False))
experiments = Table('v3_experiments', metadata, Column('id', String(64), primary_key=True), Column('payload', Text, nullable=False), Column('status', String(32), nullable=False))
families = Table('v3_families', metadata, Column('id', String(100), primary_key=True), Column('payload', Text, nullable=False))
research_locks = Table('v3_research_locks',metadata,Column('id',String(64),primary_key=True))
consumed_holdouts = Table('v3_consumed_holdouts',metadata,Column('id',String(64),primary_key=True),Column('payload',Text,nullable=False))
jobs = Table('v3_jobs', metadata, Column('id', String(64), primary_key=True), Column('payload', Text, nullable=False), Column('status', String(32), nullable=False), Column('available_at', String(40), nullable=False))
subscriptions = Table('v3_paper_subscriptions', metadata, Column('id', String(64), primary_key=True), Column('payload', Text, nullable=False))
legacy_evidence = Table('v3_legacy_evidence',metadata,Column('id',String(64),primary_key=True),Column('payload',Text,nullable=False))


class Repository:
    def __init__(self, url: str = 'sqlite:///var/blum-v3.db', *, production: bool = False):
        if production and not url.startswith('postgresql'):
            raise ValueError('production_requires_postgresql')
        if url.startswith('sqlite:///') and ':memory:' not in url:
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
        if url.startswith('postgresql://'):
            url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
        options = {'connect_args': {'check_same_thread': False, 'timeout': 30}} if url.startswith('sqlite') else {}
        if ':memory:' in url:
            options['poolclass'] = StaticPool
        self.engine = create_engine(url, pool_pre_ping=True, **options)
        self.lock = RLock()
        metadata.create_all(self.engine)
        with self.transaction() as conn:
            versions = list(conn.scalars(select(schema.c.version)))
            if versions and versions != [1]:
                raise ValueError('unsupported_schema_version')
            if not versions:
                conn.execute(insert(schema).values(version=1))

    @contextmanager
    def transaction(self, account_id: str | None = None):
        with self.lock, self.engine.connect() as conn:
            if self.engine.dialect.name == 'sqlite':
                conn.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                conn.begin()
                if account_id is not None:
                    conn.execute(select(accounts.c.id).where(accounts.c.id == account_id).with_for_update()).first()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def save_dataset(self, value: AcceptedDataset):
        payload = value.model_dump_json()
        with self.transaction() as conn:
            old = conn.scalar(select(datasets.c.payload).where(datasets.c.id == value.dataset_id))
            if old is not None:
                if old != payload:
                    raise ValueError('immutable_dataset_conflict')
                return
            conn.execute(insert(datasets).values(id=value.dataset_id, payload=payload))

    def dataset(self, dataset_id: str) -> AcceptedDataset:
        with self.engine.connect() as conn:
            payload = conn.scalar(select(datasets.c.payload).where(datasets.c.id == dataset_id))
        if payload is None:
            raise KeyError('dataset_not_found')
        return AcceptedDataset.model_validate_json(payload)

    def list_datasets(self) -> list[dict]:
        with self.engine.connect() as conn:
            rows = list(conn.scalars(select(datasets.c.payload)))
        result = []
        for raw in rows:
            value = AcceptedDataset.model_validate_json(raw)
            result.append(dict(dataset_id=value.dataset_id, instrument=value.instrument.model_dump(mode='json'),
                bars=len(value.bars), rejected=len(value.rejected), warnings=value.warnings,
                provider=value.provenance.provider, evidence_tier=value.evidence_tier,
                first=value.bars[0].timestamp.isoformat() if value.bars else None,
                last=value.bars[-1].available_at.isoformat() if value.bars else None))
        return result

    @staticmethod
    def replay_command(conn, scope: str, key: str, payload):
        if not key or len(key) > 128:
            raise ValueError('idempotency_key_required')
        row = conn.execute(select(commands).where(commands.c.scope == scope, commands.c.key == key)).mappings().first()
        if row:
            if row['fingerprint'] != identity(payload):
                raise ValueError('idempotency_conflict')
            return json.loads(row['result'])
        return None

    @staticmethod
    def lock_research(conn,instrument_id):
        if conn.dialect.name=='postgresql':
            from sqlalchemy.dialects.postgresql import insert as upsert
        else:
            from sqlalchemy.dialects.sqlite import insert as upsert
        conn.execute(upsert(research_locks).values(id=instrument_id).on_conflict_do_nothing(index_elements=['id']))
        conn.execute(select(research_locks.c.id).where(research_locks.c.id==instrument_id).with_for_update()).scalar_one()

    @staticmethod
    def remember(conn, scope: str, key: str, payload, result):
        conn.execute(insert(commands).values(scope=scope, key=key, fingerprint=identity(payload), result=encode(result)))

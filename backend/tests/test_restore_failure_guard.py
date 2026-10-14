"""Run the actual startup script against failed restore tools and an isolated backup."""
import os
from pathlib import Path
import subprocess


def test_failed_logical_restore_does_not_run_migrations_or_destroy_the_backup(tmp_path):
    fake=tmp_path/'bin'
    fake.mkdir()
    tools={'service':'exit 0', 'python3':'exit 0',
        'su':'case "$*" in *pg_restore*) exit 21;; *information_schema.tables*) echo 0;; *) exit 0;; esac'}
    for name,body in tools.items():
        path=fake/name
        path.write_text('#!/bin/sh\n'+body+'\n')
        path.chmod(0o700)
    persistence=tmp_path/'data'
    persistence.mkdir()
    backup=persistence/'embedded_postgres_blum.dump'
    backup.write_bytes(b'failed-test-backup-kept-for-recovery')
    env={**os.environ,'PATH':str(fake)+':/usr/bin:/bin','DATABASE_URL':'',
        'BLUM_PERSIST_DIR':str(persistence),'BLUM_LOCAL_POSTGRES_DATA_DIR':str(tmp_path/'local-postgres')}
    script=Path(__file__).parents[2]/'scripts/start.sh'
    result=subprocess.run(['/bin/bash',str(script)],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode!=0
    assert 'Applying Alembic migrations' not in result.stdout
    assert 'Refusing startup' in result.stdout
    assert backup.read_bytes()==b'failed-test-backup-kept-for-recovery'
    # A partial restore may have created tables. A container retry must still fail.
    (fake/'su').write_text('#!/bin/sh\ncase "$*" in *information_schema.tables*) echo 45;; *) exit 0;; esac\n')
    retry=subprocess.run(['/bin/bash',str(script)],env=env,capture_output=True,text=True,timeout=15)
    assert 'Applying Alembic migrations' not in retry.stdout
    assert 'incomplete restore' in retry.stdout


def test_unusable_physical_backup_without_logical_recovery_refuses_empty_startup(tmp_path):
    fake=tmp_path/'bin'
    fake.mkdir()
    for name,body in {'service':'exit 0','python3':'exit 0','pg_dropcluster':'exit 0',
        'pg_createcluster':'exit 0','su':'case "$*" in *information_schema.tables*) echo 0;; *) exit 0;; esac'}.items():
        path=fake/name
        path.write_text('#!/bin/sh\n'+body+'\n')
        path.chmod(0o700)
    persistence=tmp_path/'data'
    physical=persistence/'embedded_postgres_physical'
    physical.mkdir(parents=True)
    (physical/'ready').touch()
    (physical/'base.tar.gz').write_bytes(b'invalid recovery archive')
    local=tmp_path/'local-postgres'
    local.mkdir()
    env={**os.environ,'PATH':str(fake)+':/usr/bin:/bin','DATABASE_URL':'',
        'BLUM_PERSIST_DIR':str(persistence),'BLUM_LOCAL_POSTGRES_DATA_DIR':str(local)}
    script=Path(__file__).parents[2]/'scripts/start.sh'
    result=subprocess.run(['/bin/bash',str(script)],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode!=0
    assert 'Applying Alembic migrations' not in result.stdout
    assert 'Refusing startup' in result.stdout

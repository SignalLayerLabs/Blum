from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT / "scripts" / "start.sh"
RESTORE_STATUS_SERVER = ROOT / "scripts" / "restore_status_server.py"


def test_embedded_postgres_backup_uses_custom_format_and_is_atomic() -> None:
    source = START_SCRIPT.read_text()

    assert 'BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-1800}"' in source
    assert 'pg_dump -Fc -Z1 blum' in source
    assert '"${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"' in source


def test_embedded_postgres_restore_supports_custom_and_bootstrap_fallbacks() -> None:
    source = START_SCRIPT.read_text()

    assert 'embedded_postgres_blum.dump' in source
    assert 'BLUM_DB_RESTORE_JOBS="${BLUM_DB_RESTORE_JOBS:-2}"' in source
    assert 'pg_restore --jobs=${BLUM_DB_RESTORE_JOBS} --exit-on-error -d blum' in source
    assert '< "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}"' not in source
    assert 'embedded_postgres_blum.sql.gz' in source
    assert 'gzip -dc "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}"' in source
    assert 'embedded_postgres_blum.sql.gz.parts-ready' in source
    assert '"${BLUM_COMPRESSED_POSTGRES_PART_PREFIX}".part-*' in source
    assert 'embedded_postgres_blum.sql"' in source
    assert 'Restoring legacy PostgreSQL backup' in source
    assert "BLUM_LEGACY_POSTGRES_BACKUP_FILE" in source
    assert 'su postgres -c "psql -v ON_ERROR_STOP=1 -d blum" < "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}"' in source
    assert 'psql -d blum < \\"${BLUM_LEGACY_POSTGRES_BACKUP_FILE}\\"' not in source


def test_embedded_postgres_prefers_a_local_restore_from_physical_backup() -> None:
    source = START_SCRIPT.read_text()

    assert 'embedded_postgres_physical/base.tar.gz' in source
    assert 'embedded_postgres_physical/ready' in source
    assert '[[ -f "${BLUM_PHYSICAL_POSTGRES_READY_FILE}" ]]' in source
    assert 'restore_embedded_postgres_physical_backup' in source
    assert 'tar -xzf "${BLUM_PHYSICAL_POSTGRES_BASE_BACKUP}"' in source
    assert 'service postgresql start' in source
    assert source.index('restore_embedded_postgres_physical_backup') < source.index('service postgresql start')
    assert 'PHYSICAL_RESTORE_ATTEMPTED=false' in source
    assert 'Physical PostgreSQL recovery image extraction failed; falling back to logical restore.' in source
    assert 'reset_local_postgres_cluster' in source


def test_physical_backup_is_built_locally_then_published_atomically() -> None:
    source = START_SCRIPT.read_text()

    assert 'backup_embedded_postgres_physical' in source
    assert 'publish_embedded_postgres_physical_backup' in source
    assert 'pg_basebackup -D \'${physical_tmp_dir}\'' in source
    assert 'BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR' in source
    assert 'touch "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}/ready"' in source
    assert 'mv "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}" "${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}"' in source
    assert 'mv "${previous_backup_dir}" "${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}" || true' in source
    assert 'backup_embedded_postgres_physical || true' in source


def test_backup_worker_warms_physical_snapshot_without_blocking_api_start() -> None:
    source = START_SCRIPT.read_text()

    assert 'BLUM_DB_INITIAL_BACKUP_DELAY_SECONDS="${BLUM_DB_INITIAL_BACKUP_DELAY_SECONDS:-60}"' in source
    assert 'sleep "${BLUM_DB_INITIAL_BACKUP_DELAY_SECONDS}"' in source
    assert source.index('alembic -c alembic.ini upgrade head') < source.rindex('start_backup_loop')


def test_failed_network_postgres_cluster_is_removed_only_when_recovery_dump_exists() -> None:
    source = START_SCRIPT.read_text()

    assert 'cleanup_unsupported_persistent_postgres' in source
    assert 'embedded_postgres_blum.dump' in source
    assert 'rm -rf "${unsupported_data_dir}"' in source


def test_restore_exposes_a_non_blank_status_page_before_the_api_is_ready() -> None:
    source = START_SCRIPT.read_text()
    status_server = RESTORE_STATUS_SERVER.read_text()

    assert "start_restore_status_server" in source
    assert "restore_status_server.py" in source
    assert '"/health", "/startup/status"' in status_server
    assert '"healthy": True' in status_server
    assert '"api_ready": False' in status_server
    assert "BLUM is restoring its learning memory" in status_server
    assert "stop_restore_status_server" in source

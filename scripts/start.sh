#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export BLUM_PERSIST_DIR="${BLUM_PERSIST_DIR:-/data/blum}"
export BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-1800}"
export BLUM_DB_RESTORE_JOBS="${BLUM_DB_RESTORE_JOBS:-2}"
export BLUM_DB_INITIAL_BACKUP_DELAY_SECONDS="${BLUM_DB_INITIAL_BACKUP_DELAY_SECONDS:-60}"
export BLUM_LOCAL_POSTGRES_DATA_DIR="${BLUM_LOCAL_POSTGRES_DATA_DIR:-/var/lib/postgresql/15/main}"
BLUM_LOCAL_RESTORE_INCOMPLETE_FILE="${BLUM_LOCAL_POSTGRES_DATA_DIR}.restore-incomplete"
export BLUM_PHYSICAL_POSTGRES_BACKUP_DIR="${BLUM_PERSIST_DIR}/embedded_postgres_physical"
export BLUM_PHYSICAL_POSTGRES_BASE_BACKUP="${BLUM_PERSIST_DIR}/embedded_postgres_physical/base.tar.gz"
export BLUM_PHYSICAL_POSTGRES_WAL_BACKUP="${BLUM_PERSIST_DIR}/embedded_postgres_physical/pg_wal.tar.gz"
export BLUM_PHYSICAL_POSTGRES_READY_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_physical/ready"
export BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR="${BLUM_PERSIST_DIR}/embedded_postgres_physical.publishing"
RESTORE_STATUS_PID=""
START_EMBEDDED_BACKUP_LOOP=false

start_restore_status_server() {
  if [[ -n "${RESTORE_STATUS_PID}" ]] && kill -0 "${RESTORE_STATUS_PID}" 2>/dev/null; then
    return 0
  fi
  python3 /app/scripts/restore_status_server.py >/tmp/blum-restore-status.log 2>&1 &
  RESTORE_STATUS_PID=$!
}

stop_restore_status_server() {
  if [[ -n "${RESTORE_STATUS_PID}" ]] && kill -0 "${RESTORE_STATUS_PID}" 2>/dev/null; then
    kill "${RESTORE_STATUS_PID}" 2>/dev/null || true
    wait "${RESTORE_STATUS_PID}" 2>/dev/null || true
  fi
  RESTORE_STATUS_PID=""
}

backup_embedded_postgres() {
  if [[ -n "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE:-}" ]]; then
    mkdir -p "$(dirname "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}")" || true
    if su postgres -c "pg_dump -Fc -Z1 blum" > "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"; then
      mv "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp" "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}"
      echo "Embedded PostgreSQL backup updated at ${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}."
    else
      echo "Embedded PostgreSQL backup failed; keeping previous backup if present."
      rm -f "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"
    fi
  fi
}

publish_embedded_postgres_physical_backup() {
  local physical_tmp_dir="$1"
  local previous_backup_dir="${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}.previous"

  rm -rf "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}"
  mkdir -p "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}" || return 1
  cp "${physical_tmp_dir}/base.tar.gz" "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}/base.tar.gz" || return 1
  if [[ -s "${physical_tmp_dir}/pg_wal.tar.gz" ]]; then
    cp "${physical_tmp_dir}/pg_wal.tar.gz" "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}/pg_wal.tar.gz" || return 1
  fi
  touch "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}/ready" || return 1

  rm -rf "${previous_backup_dir}"
  if [[ -d "${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}" ]]; then
    mv "${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}" "${previous_backup_dir}" || return 1
  fi
  if ! mv "${BLUM_PHYSICAL_POSTGRES_PUBLISH_DIR}" "${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}"; then
    mv "${previous_backup_dir}" "${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}" || true
    return 1
  fi
  rm -rf "${previous_backup_dir}"
}

backup_embedded_postgres_physical() {
  local physical_tmp_dir=""

  physical_tmp_dir="$(mktemp -d /tmp/blum-postgres-physical.XXXXXX)"
  chown postgres:postgres "${physical_tmp_dir}"
  if su postgres -c "pg_basebackup -D '${physical_tmp_dir}' -Ft -z -X stream -c fast" \
    && [[ -s "${physical_tmp_dir}/base.tar.gz" ]] \
    && publish_embedded_postgres_physical_backup "${physical_tmp_dir}"; then
    echo "Embedded PostgreSQL physical backup updated at ${BLUM_PHYSICAL_POSTGRES_BACKUP_DIR}."
  else
    echo "Embedded PostgreSQL physical backup failed; keeping the previous recovery image."
  fi
  rm -rf "${physical_tmp_dir}"
}

start_backup_loop() {
  if [[ -n "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE:-}" ]]; then
    (
      sleep "${BLUM_DB_INITIAL_BACKUP_DELAY_SECONDS}"
      while true; do
        backup_embedded_postgres
        backup_embedded_postgres_physical || true
        sleep "${BLUM_DB_BACKUP_SECONDS}"
      done
    ) &
  fi
}

restore_embedded_postgres_physical_backup() {
  [[ -f "${BLUM_PHYSICAL_POSTGRES_READY_FILE}" ]] || return 1
  [[ -s "${BLUM_PHYSICAL_POSTGRES_BASE_BACKUP}" ]] || return 1

  echo "Restoring local PostgreSQL data directory from the physical recovery image."
  service postgresql stop >/dev/null 2>&1 || true
  rm -rf "${BLUM_LOCAL_POSTGRES_DATA_DIR:?}"/*
  if ! tar -xzf "${BLUM_PHYSICAL_POSTGRES_BASE_BACKUP}" -C "${BLUM_LOCAL_POSTGRES_DATA_DIR}"; then
    return 1
  fi
  if [[ -s "${BLUM_PHYSICAL_POSTGRES_WAL_BACKUP}" ]]; then
    mkdir -p "${BLUM_LOCAL_POSTGRES_DATA_DIR}/pg_wal"
    if ! tar -xzf "${BLUM_PHYSICAL_POSTGRES_WAL_BACKUP}" -C "${BLUM_LOCAL_POSTGRES_DATA_DIR}/pg_wal"; then
      return 1
    fi
  fi
  rm -f "${BLUM_LOCAL_POSTGRES_DATA_DIR}/postmaster.pid"
  chown -R postgres:postgres "${BLUM_LOCAL_POSTGRES_DATA_DIR}"
  chmod 700 "${BLUM_LOCAL_POSTGRES_DATA_DIR}"
}

reset_local_postgres_cluster() {
  service postgresql stop >/dev/null 2>&1 || true
  pg_dropcluster --stop 15 main >/dev/null 2>&1 || true
  pg_createcluster 15 main >/dev/null
}

cleanup_unsupported_persistent_postgres() {
  local unsupported_data_dir="${BLUM_PERSIST_DIR}/postgresql"
  local recovery_dump="${BLUM_PERSIST_DIR}/embedded_postgres_blum.dump"

  if [[ -d "${unsupported_data_dir}" && -s "${recovery_dump}" ]]; then
    echo "Removing unsupported PostgreSQL network-volume data directory; the recovery dump remains authoritative."
    rm -rf "${unsupported_data_dir}"
  fi
}

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "No DATABASE_URL provided. Starting embedded PostgreSQL for the Hugging Face Docker demo."
  if [[ -f "${BLUM_LOCAL_RESTORE_INCOMPLETE_FILE}" ]]; then
    echo "Refusing startup after an incomplete restore. Recover the local database before clearing its failure marker."
    exit 1
  fi
  mkdir -p "${BLUM_PERSIST_DIR}" || true
  cleanup_unsupported_persistent_postgres
  PHYSICAL_RESTORE_ATTEMPTED=false
  if [[ -f "${BLUM_PHYSICAL_POSTGRES_READY_FILE}" ]]; then
    PHYSICAL_RESTORE_ATTEMPTED=true
    touch "${BLUM_LOCAL_RESTORE_INCOMPLETE_FILE}"
    start_restore_status_server
    if restore_embedded_postgres_physical_backup; then
      echo "Physical PostgreSQL recovery image restored to local disk."
    else
      echo "Physical PostgreSQL recovery image extraction failed; falling back to logical restore."
      mv "${BLUM_PHYSICAL_POSTGRES_READY_FILE}" "${BLUM_PHYSICAL_POSTGRES_READY_FILE}.invalid" || true
      reset_local_postgres_cluster
    fi
  fi
  if ! service postgresql start; then
    if [[ "${PHYSICAL_RESTORE_ATTEMPTED}" != "true" ]]; then
      echo "Embedded PostgreSQL failed to start without a physical restore fallback."
      exit 1
    fi
    echo "Physical PostgreSQL recovery image was unusable; falling back to logical restore."
    mv "${BLUM_PHYSICAL_POSTGRES_READY_FILE}" "${BLUM_PHYSICAL_POSTGRES_READY_FILE}.invalid" || true
    reset_local_postgres_cluster
    service postgresql start
  fi
  su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='blum'\" | grep -q 1 || createdb blum"
  su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres';\""
  export BLUM_EMBEDDED_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.dump"
  export BLUM_COMPRESSED_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz"
  export BLUM_COMPRESSED_POSTGRES_PART_PREFIX="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz"
  export BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz.parts-ready"
  export BLUM_LEGACY_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql"
  TABLE_COUNT="$(su postgres -c "psql -d blum -tAc \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public';\"" | tr -d '[:space:]')"
  if [[ "${TABLE_COUNT:-0}" == "0" && "${PHYSICAL_RESTORE_ATTEMPTED}" == "true" ]] && ! { [[ -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE}" ]] || [[ -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; }; then
    echo "Refusing startup: physical recovery left no financial tables and no logical backup is available."
    stop_restore_status_server
    exit 1
  fi
  if [[ "${TABLE_COUNT:-0}" == "0" ]] && { [[ -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE}" ]] || [[ -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; }; then
    start_restore_status_server
  fi
  if [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]]; then
    echo "Restoring embedded PostgreSQL backup from ${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}."
    chmod a+r "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" || true
    touch "${BLUM_LOCAL_RESTORE_INCOMPLETE_FILE}"
    if ! su postgres -c "pg_restore --jobs=${BLUM_DB_RESTORE_JOBS} --exit-on-error -d blum '${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}'"; then
      echo "Custom backup restore failed. Refusing startup with incomplete financial evidence."
      stop_restore_status_server
      exit 1
    fi
  elif [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" ]]; then
    echo "Restoring compressed PostgreSQL bootstrap from ${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}."
    touch "${BLUM_LOCAL_RESTORE_INCOMPLETE_FILE}"
    if ! gzip -dc "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" | su postgres -c "psql -v ON_ERROR_STOP=1 -d blum"; then
      echo "Compressed backup restore failed. Refusing startup with incomplete financial evidence."
      stop_restore_status_server
      exit 1
    fi
  elif [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE}" ]]; then
    echo "Restoring segmented PostgreSQL bootstrap from ${BLUM_COMPRESSED_POSTGRES_PART_PREFIX}.part-* ."
    touch "${BLUM_LOCAL_RESTORE_INCOMPLETE_FILE}"
    if ! cat "${BLUM_COMPRESSED_POSTGRES_PART_PREFIX}".part-* | gzip -dc | su postgres -c "psql -v ON_ERROR_STOP=1 -d blum"; then
      echo "Segmented backup restore failed. Refusing startup with incomplete financial evidence."
      stop_restore_status_server
      exit 1
    fi
  elif [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; then
    echo "Restoring legacy PostgreSQL backup from ${BLUM_LEGACY_POSTGRES_BACKUP_FILE}."
    touch "${BLUM_LOCAL_RESTORE_INCOMPLETE_FILE}"
    if ! su postgres -c "psql -v ON_ERROR_STOP=1 -d blum" < "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}"; then
      echo "Legacy backup restore failed. Refusing startup with incomplete financial evidence."
      stop_restore_status_server
      exit 1
    fi
  elif [[ ! -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" && ! -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" && ! -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; then
    echo "No embedded PostgreSQL backup found yet. A new backup will be written periodically."
  else
    echo "Embedded PostgreSQL already contains tables; skipping restore."
  fi
  rm -f "${BLUM_LOCAL_RESTORE_INCOMPLETE_FILE}"
  stop_restore_status_server
  export DATABASE_URL="postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum"
  START_EMBEDDED_BACKUP_LOOP=true
else
  echo "Using external PostgreSQL DATABASE_URL."
fi

echo "Applying Alembic migrations."
cd /app/backend
alembic -c alembic.ini upgrade head

if [[ "${START_EMBEDDED_BACKUP_LOOP}" == "true" ]]; then
  start_backup_loop
fi

cd /app
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"

#!/bin/sh
# =============================================================================
# Container entrypoint.
#
# Waits for PostgreSQL, migrates, ensures the audit partitions exist, collects
# static files, then exec's the command so that it becomes PID 1 and receives
# SIGTERM directly. Without the exec, gunicorn would be a child of this shell
# and would never see the signal, so every deploy would end in a SIGKILL after
# the grace period.
# =============================================================================
set -eu

: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_USER:=srerp}"
: "${POSTGRES_DB:=srerp}"
: "${DB_WAIT_SECONDS:=60}"

log() { echo "[entrypoint] $*"; }

log "waiting for postgres at ${POSTGRES_HOST}:${POSTGRES_PORT} (up to ${DB_WAIT_SECONDS}s)"
waited=0
until pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    waited=$((waited + 1))
    if [ "$waited" -ge "$DB_WAIT_SECONDS" ]; then
        log "postgres did not become ready in ${DB_WAIT_SECONDS}s; giving up"
        exit 1
    fi
    sleep 1
done
log "postgres is ready after ${waited}s"

# NOTE: with more than one replica this races — two containers can run migrate
# at the same moment. Acceptable for a single container, and the first thing to
# change when a second replica appears: move migrate into a pre-deploy job or
# an init container. Recorded in IMPLEMENTATION.md.
log "applying migrations"
python manage.py migrate --noinput

# D10. Idempotent, so running it on every boot costs one query when there is
# nothing to do. A missing partition aborts the business transaction that
# provoked the audit write, not merely the audit row — so this is an
# availability concern, not housekeeping.
log "ensuring audit log partitions"
python manage.py ensure_audit_partitions

log "collecting static files into ${DJANGO_STATIC_ROOT:-/tmp/static}"
python manage.py collectstatic --noinput --clear >/dev/null

log "starting: $*"
exec "$@"

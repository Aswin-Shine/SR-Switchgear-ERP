#!/usr/bin/env bash
# Dumps the running `db` container (see docker-compose.yml) to a timestamped,
# gzipped SQL file. Requires the stack to be up (`docker compose up -d db`).
#
# Usage: ./db/backup.sh [output-dir]   # default: db/backups/
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."  # repo root, so `docker compose` finds docker-compose.yml

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
POSTGRES_DB="${POSTGRES_DB:-srerp}"
POSTGRES_USER="${POSTGRES_USER:-srerp}"

OUT_DIR="${1:-db/backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_FILE="$OUT_DIR/${POSTGRES_DB}-${STAMP}.sql.gz"

echo "Backing up '$POSTGRES_DB' from the running db container..."
# --clean --if-exists so the dump is self-contained: restoring it drops and
# recreates everything, instead of failing against a non-empty database.
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  | gzip > "$OUT_FILE"

echo "Wrote $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"

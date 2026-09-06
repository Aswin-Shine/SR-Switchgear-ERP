#!/usr/bin/env bash
# Restores a db/backup.sh dump into the running `db` container. Destructive —
# the dump was taken with --clean --if-exists, so this drops and recreates
# everything the dump covers.
#
# Usage: ./db/restore.sh path/to/dump.sql.gz
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."  # repo root, so `docker compose` finds docker-compose.yml

if [ $# -lt 1 ]; then
  echo "Usage: $0 <dump-file.sql.gz|dump-file.sql>" >&2
  exit 1
fi
DUMP_FILE="$1"
[ -f "$DUMP_FILE" ] || { echo "No such file: $DUMP_FILE" >&2; exit 1; }

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
POSTGRES_DB="${POSTGRES_DB:-srerp}"
POSTGRES_USER="${POSTGRES_USER:-srerp}"

echo "This REPLACES all data in '$POSTGRES_DB' with the contents of $DUMP_FILE."
read -r -p "Type the database name ($POSTGRES_DB) to confirm: " CONFIRM
if [ "$CONFIRM" != "$POSTGRES_DB" ]; then
  echo "Confirmation did not match — aborted, nothing was touched." >&2
  exit 1
fi

echo "Restoring..."
if [[ "$DUMP_FILE" == *.gz ]]; then
  gunzip -c "$DUMP_FILE" | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
else
  docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$DUMP_FILE"
fi

echo "Restore complete."

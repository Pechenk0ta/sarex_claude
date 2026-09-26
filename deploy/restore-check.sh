#!/usr/bin/env bash
# Proves a backup can be restored: loads it into a temporary database, counts rows, drops it.
# Usage: deploy/restore-check.sh /var/backups/rd/rd-YYYYMMDD-HHMMSS.dump
set -euo pipefail
cd "$(dirname "$0")/.."
dump="${1:?path to a .dump file}"
compose=(docker compose -f docker-compose.yml)

"${compose[@]}" exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists rd_restore_check && createdb -U "$POSTGRES_USER" rd_restore_check'
"${compose[@]}" exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d rd_restore_check --no-owner' < "$dump"
"${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d rd_restore_check -Atc "select '\''projects: '\'' || count(*) from projects; select '\''notifications: '\'' || count(*) from notifications; select '\''events: '\'' || count(*) from notification_events;"'
"${compose[@]}" exec -T db sh -c 'dropdb -U "$POSTGRES_USER" rd_restore_check'
echo "Restore check passed."

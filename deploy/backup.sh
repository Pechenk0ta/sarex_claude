#!/usr/bin/env bash
# Daily database backup. Run from cron on the server, see deploy/README.md.
#   BACKUP_DIR     where dumps are kept (default /var/backups/rd)
#   KEEP_DAYS      how many days to keep (default 14)
#   RCLONE_REMOTE  optional off-server copy, e.g. "s3:rd-backups" (needs rclone configured)
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-/var/backups/rd}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/rd-$(date +%Y%m%d-%H%M%S).dump"

docker compose -f docker-compose.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$file.tmp"
mv "$file.tmp" "$file"
echo "Backup written: $file ($(du -h "$file" | cut -f1))"

find "$BACKUP_DIR" -name 'rd-*.dump' -mtime +"$KEEP_DAYS" -delete

if [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$file" "$RCLONE_REMOTE"
  echo "Copied to $RCLONE_REMOTE"
fi

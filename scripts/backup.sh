#!/usr/bin/env bash
# Back up the Weekly Outcomes Review MySQL database.
# Reads DB_* settings from the application's .env file.
#   scripts/backup.sh [backup-directory]
# Schedule daily with cron, e.g.:
#   15 2 * * * /opt/weekly-outcomes/scripts/backup.sh /var/backups/weekly-outcomes
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${1:-$APP_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

set -a
# shellcheck disable=SC1091
source "$APP_DIR/.env"
set +a

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/${DB_NAME}-${STAMP}.sql.gz"

# Credentials go through a temporary option file so they never appear in `ps`.
CNF="$(mktemp)"
trap 'rm -f "$CNF"' EXIT
chmod 600 "$CNF"
cat > "$CNF" <<CNF
[client]
user=${DB_USER}
password=${DB_PASSWORD}
host=${DB_HOST:-127.0.0.1}
port=${DB_PORT:-3306}
CNF

mysqldump --defaults-extra-file="$CNF" --single-transaction --routines --triggers \
  --default-character-set=utf8mb4 --no-tablespaces "$DB_NAME" | gzip -9 > "$OUT"
chmod 600 "$OUT"

# Verify the archive is readable and contains the reports table.
gzip -t "$OUT"
zcat "$OUT" | grep -q "CREATE TABLE \`reviews_weeklyreview\`" || { echo "Backup verification failed" >&2; exit 1; }

find "$BACKUP_DIR" -name "${DB_NAME}-*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "Backup written: $OUT"

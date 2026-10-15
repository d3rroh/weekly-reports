#!/usr/bin/env bash
# Restore a backup produced by scripts/backup.sh into the configured database.
#   scripts/restore.sh /path/to/weekly_outcomes-YYYYMMDD-HHMMSS.sql.gz
# This REPLACES the current contents of DB_NAME. Stop the application first.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${1:?Usage: restore.sh <backup.sql.gz>}"
[ -f "$FILE" ] || { echo "No such file: $FILE" >&2; exit 1; }

set -a
# shellcheck disable=SC1091
source "$APP_DIR/.env"
set +a

read -r -p "Restore $FILE into database '$DB_NAME' on ${DB_HOST:-127.0.0.1}? This overwrites existing data. Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "Aborted."; exit 1; }

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

gzip -t "$FILE"
zcat "$FILE" | mysql --defaults-extra-file="$CNF" --default-character-set=utf8mb4 "$DB_NAME"
echo "Restore complete. Run: python manage.py migrate && python manage.py check"

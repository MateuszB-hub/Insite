#!/usr/bin/env bash
# Restore an Insite backup.
#
#   ./scripts/restore_db.sh ~/Insite-Backups/insite-20260925T120000Z.sql.gz.enc
#
# DESTRUCTIVE: the dump is taken with --clean --if-exists, so it drops and
# recreates every object it contains. Read it before running it in anger.
set -euo pipefail

FILE="${1:?usage: restore_db.sh <backup.sql.gz.enc> [--yes]}"
CONFIRM="${2:-}"
DOCKER="${DOCKER_BIN:-$HOME/.docker/bin/docker}"
CONTAINER="${PG_CONTAINER:-insite-db}"
DB_USER="${POSTGRES_USER:-insite}"
DB_NAME="${POSTGRES_DB:-insite}"
PASS_FILE="${BACKUP_PASS_FILE:-$HOME/.insite-backup-pass}"

[ -f "$FILE" ] || { echo "no such backup: $FILE" >&2; exit 1; }
[ -f "$PASS_FILE" ] || { echo "no passphrase at $PASS_FILE" >&2; exit 1; }

if [ "$CONFIRM" != "--yes" ]; then
  echo "About to OVERWRITE database '$DB_NAME' in container '$CONTAINER'"
  echo "from $(basename "$FILE")."
  printf 'Type the database name to continue: '
  read -r answer
  [ "$answer" = "$DB_NAME" ] || { echo "aborted"; exit 1; }
fi

/usr/bin/openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
    -pass "file:$PASS_FILE" -in "$FILE" \
  | /usr/bin/gzip -dc \
  | "$DOCKER" exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
  > /dev/null

echo "restored $DB_NAME from $(basename "$FILE")"

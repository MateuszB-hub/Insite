#!/usr/bin/env bash
# Encrypted Postgres backup for Insite.
#
#   ./scripts/backup_db.sh
#
# Design notes:
#
#  * The dump contains applicant PII (emails, names, cover letters), so it is
#    encrypted with AES-256 BEFORE anything copies it off this machine. The
#    passphrase lives in a 0600 file on local disk and is deliberately NOT
#    synced anywhere -- a backup and its key in the same cloud account is not
#    two copies, it is one.
#  * A local copy gives fast recovery from "I dropped the wrong table". The
#    offsite copy covers disk failure and theft. Both are needed.
#  * Absolute paths throughout: cron and launchd run with a minimal PATH and
#    will not find `docker` on their own.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER="${DOCKER_BIN:-$HOME/.docker/bin/docker}"
CONTAINER="${PG_CONTAINER:-insite-db}"
DB_USER="${POSTGRES_USER:-insite}"
DB_NAME="${POSTGRES_DB:-insite}"

LOCAL_DIR="${BACKUP_DIR:-$HOME/Insite-Backups}"
OFFSITE_DIR="${BACKUP_OFFSITE_DIR:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Insite-Backups}"
PASS_FILE="${BACKUP_PASS_FILE:-$HOME/.insite-backup-pass}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
LOG="${BACKUP_LOG:-$LOCAL_DIR/backup.log}"

mkdir -p "$LOCAL_DIR"

log() { printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$LOG"; }
fail() { log "FAILED: $*"; exit 1; }

[ -x "$DOCKER" ] || fail "docker not found at $DOCKER (set DOCKER_BIN)"

if [ ! -f "$PASS_FILE" ]; then
  # Generate once, then never change it without keeping the old one: old
  # backups can only be opened with the passphrase that made them.
  umask 077
  /usr/bin/openssl rand -base64 48 > "$PASS_FILE"
  chmod 600 "$PASS_FILE"
  log "generated a new backup passphrase at $PASS_FILE -- BACK THIS UP SEPARATELY"
fi

"$DOCKER" inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true \
  || fail "container $CONTAINER is not running (is Docker Desktop up?)"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT="$LOCAL_DIR/insite-$STAMP.sql.gz.enc"

# pg_dump | gzip | encrypt, all streamed: the plaintext never touches disk.
if ! "$DOCKER" exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    | /usr/bin/gzip -9 \
    | /usr/bin/openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
        -pass "file:$PASS_FILE" -out "$OUT"; then
  rm -f "$OUT"
  fail "pg_dump pipeline failed"
fi

SIZE=$(/usr/bin/stat -f%z "$OUT")
[ "$SIZE" -gt 1000 ] || { rm -f "$OUT"; fail "backup suspiciously small ($SIZE bytes)"; }

# Prove it decrypts and looks like SQL. An untested backup is a guess.
if ! /usr/bin/openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
      -pass "file:$PASS_FILE" -in "$OUT" \
      | /usr/bin/gzip -dc | /usr/bin/head -40 | /usr/bin/grep -q "PostgreSQL database dump"; then
  fail "verification failed: $OUT did not decrypt to a valid dump"
fi

log "wrote $(basename "$OUT") ($((SIZE / 1024)) KB, verified)"

# Offsite is best-effort and must NEVER fail the backup. iCloud Drive is
# TCC-protected, and under launchd the copy succeeds while a `find` sweep of
# the same directory returns "Operation not permitted" -- losing a good,
# verified backup to a failed cleanup would be absurd.
if mkdir -p "$OFFSITE_DIR" 2>/dev/null && cp "$OUT" "$OFFSITE_DIR/" 2>/dev/null; then
  log "copied offsite to $OFFSITE_DIR"
else
  log "WARNING: offsite copy failed; this backup exists on ONE machine only"
fi

# Rotate by age. Local is authoritative; offsite rotation is best-effort.
/usr/bin/find "$LOCAL_DIR" -name 'insite-*.sql.gz.enc' -type f -mtime +"$KEEP_DAYS" -delete
if [ -d "$OFFSITE_DIR" ]; then
  /usr/bin/find "$OFFSITE_DIR" -name 'insite-*.sql.gz.enc' -type f -mtime +"$KEEP_DAYS" -delete \
    2>/dev/null || log "note: could not rotate offsite copies (TCC); prune manually"
fi

log "done. local copies: $(/usr/bin/find "$LOCAL_DIR" -name 'insite-*.enc' | /usr/bin/wc -l | /usr/bin/tr -d ' ')"

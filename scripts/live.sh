#!/usr/bin/env bash
# Run Insite's staging and live sites as background services.
#
#   ./scripts/live.sh stage             deploy this checkout to STAGING
#   ./scripts/live.sh promote           deploy this checkout to LIVE -- only
#                                       the exact commit staging is running
#   ./scripts/live.sh deploy            legacy: working copy straight to live,
#                                       no checks (kept until the pipeline
#                                       cutover is verified; urgent fixes only)
#   ./scripts/live.sh rollback [live|staging]   back to the release before
#                                       the last deploy (app files only)
#   ./scripts/live.sh verify ENV SHA    exit non-zero unless ENV answers and
#                                       runs commit SHA (used by CI)
#   ./scripts/live.sh refresh-staging   copy the newest live backup into the
#                                       staging database
#   ./scripts/live.sh status  [live|staging|all]   (default: all)
#   ./scripts/live.sh logs    [live|staging]       (default: live)
#   ./scripts/live.sh restart [live|staging]
#   ./scripts/live.sh stop    [live|staging]
#
# Release flow: tag a commit (vYYYY.MM.DD-N) -> stage -> check staging ->
# promote. `stage` refuses uncommitted code; `promote` also needs a release
# tag and refuses anything staging isn't running, so what reaches visitors
# is always something that was checked on staging first.
#
# Why each environment runs from a COPY (~/Insite-Live, ~/Insite-Staging):
#  * ~/Documents is protected by macOS TCC, and a launchd agent reading from
#    it fails with "Operation not permitted" unless /bin/bash is granted Full
#    Disk Access -- far too broad (same reason as install_backup.sh).
#  * Editing code here never changes a running site underneath visitors.
#
# Services start at login and restart themselves if they crash. Live keeps
# the Mac awake while it runs (on power, lid open). Live serves on :8080,
# staging on :8081; the Cloudflare tunnel points each hostname at its port.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="gui/$(id -u)"
# Real env files live outside ~/Documents (TCC) and outside any checkout, so
# a CI runner's clone deploys with the same secrets. backend/.env and
# backend/.env.production are symlinks here for dev.sh.
SECRETS="${INSITE_SECRETS_DIR:-$HOME/.config/insite}"
BACKUPS="${INSITE_BACKUP_DIR:-$HOME/Insite-Backups}"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# use_env live|staging -- every other function reads these.
use_env() {
  ENV="$1"
  case "$ENV" in
    live)
      LABEL="com.insite.web"
      DIR="${INSITE_LIVE_DIR:-$HOME/Insite-Live}"
      PORT=8080
      ENV_FILE=".env.production"
      DB_EXPECTED="insite"
      URL="https://app.mateuszbieda.dev"
      KEEP_AWAKE=true
      ;;
    staging)
      LABEL="com.insite.staging"
      DIR="${INSITE_STAGING_DIR:-$HOME/Insite-Staging}"
      PORT=8081
      ENV_FILE=".env.staging"
      DB_EXPECTED="insite_staging"
      URL="https://staging.mateuszbieda.dev"
      KEEP_AWAKE=false
      ;;
    *) die "unknown environment '$ENV' (use live or staging)" ;;
  esac
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
}

healthy() { curl -sf -m 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; }
loaded() { launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }

wait_healthy() {
  for _ in $(seq 1 60); do
    healthy && return 0
    sleep 1
  done
  return 1
}

start() {
  if loaded; then
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    # bootout also returns before launchd has finished removing the service,
    # and bootstrapping it again in that window fails with
    # "Bootstrap failed: 5: Input/output error".
    for _ in $(seq 1 20); do
      loaded || break
      sleep 0.5
    done
  fi
  # bootout returns before the old process has fully released the port.
  for _ in $(seq 1 20); do
    lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.5
  done
  launchctl bootstrap "$DOMAIN" "$PLIST"
  say "-> waiting for $ENV to answer on :$PORT"
  if wait_healthy; then
    say "OK  $ENV is up: $URL"
  else
    say "!!  not answering after 60s. Last log lines:"
    tail -n 25 "$DIR/logs/web.err.log" 2>/dev/null || true
    exit 1
  fi
}

# --- release checks -------------------------------------------------------

head_commit() { git -C "$ROOT" rev-parse HEAD; }
head_tag() { git -C "$ROOT" describe --tags --exact-match HEAD 2>/dev/null || true; }

require_clean() {
  git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT is not a git checkout"
  if ! git -C "$ROOT" diff --quiet || ! git -C "$ROOT" diff --cached --quiet; then
    die "uncommitted changes. Commit them first -- a deploy must be reproducible."
  fi
}

# Live additionally needs a release tag; staging takes any committed code.
require_release() {
  require_clean
  [ -n "$(head_tag)" ] || die "this commit has no release tag. Tag it first, e.g.:
   git tag v$(date +%Y.%m.%d)-1 && git push origin --tags"
}

# The commit a deployed copy is running ("" if unknown).
deployed_commit() { [ -f "$1/VERSION" ] && awk '{print $2}' "$1/VERSION" || true; }

# --- deploy ---------------------------------------------------------------

# The database this environment would actually connect to, resolved the same
# way serve.sh does (.env, then the environment's overlay wins).
resolved_db() {
  (
    set -a
    . "$SECRETS/.env"
    . "$SECRETS/$ENV_FILE"
    set +a
    url="${DATABASE_URL:-}"
    url="${url%%\?*}"
    printf '%s' "${url##*/}"
  )
}

base_python() {
  local uv
  uv="$(command -v uv || echo "$HOME/.local/bin/uv")"
  if [ -x "$uv" ]; then
    "$uv" python find 3.12
  else
    "$ROOT/backend/.venv/bin/python" -c 'import sys; print(sys._base_executable)'
  fi
}

deploy_to() {
  [ -f "$SECRETS/.env" ] || die "$SECRETS/.env missing"
  [ -f "$SECRETS/$ENV_FILE" ] || die "$SECRETS/$ENV_FILE missing"

  # Never let a settings mistake point an environment at another's data.
  db="$(resolved_db)"
  [ "$db" = "$DB_EXPECTED" ] || die "$ENV would use database '$db', expected '$DB_EXPECTED'.
   Set DATABASE_URL in $SECRETS/$ENV_FILE."

  # A foreground serve.sh (Terminal) would hold the port.
  if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 && ! loaded; then
    die "something is already serving on :$PORT -- probably serve.sh in a
Terminal window. Press Ctrl+C there first, then re-run this."
  fi

  say "-> building frontend"
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    ( cd "$ROOT/frontend" && npm ci --silent ) || die "npm ci failed"
  fi
  ( cd "$ROOT/frontend" && npm run build >/dev/null ) || die "frontend build failed"

  # Keep the release being replaced, so `rollback` is one step. App files
  # only: database migrations are not undone, which is why they must stay
  # additive (a new column the old code simply ignores).
  if [ -f "$DIR/VERSION" ]; then
    say "-> keeping the current release in $DIR.prev"
    rsync -a --delete --exclude 'logs/' "$DIR/" "$DIR.prev/"
  fi

  say "-> copying app to $DIR"
  mkdir -p "$DIR/backend" "$DIR/frontend" "$DIR/logs"
  # --delete removes files deleted here; excluded paths (the deployed venv
  # and secrets) are never touched by it.
  rsync -a --delete \
    --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
    --exclude 'tests/' --exclude '.env*' \
    "$ROOT/backend/" "$DIR/backend/"
  rsync -a --delete "$ROOT/frontend/dist/" "$DIR/frontend/dist/"
  install -m 755 "$ROOT/serve.sh" "$DIR/serve.sh"
  install -m 600 "$SECRETS/.env" "$DIR/backend/.env"
  install -m 600 "$SECRETS/$ENV_FILE" "$DIR/backend/$ENV_FILE"

  say "-> python environment"
  PY="$(base_python)"
  case "$PY" in "$HOME/Documents"*) die "base python lives in ~/Documents ($PY)";; esac
  if command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ]; then
    uv="$(command -v uv || echo "$HOME/.local/bin/uv")"
    [ -x "$DIR/backend/.venv/bin/python" ] || "$uv" venv -q --python "$PY" "$DIR/backend/.venv"
    "$uv" pip install -q --python "$DIR/backend/.venv/bin/python" -r "$DIR/backend/requirements.txt"
  else
    [ -x "$DIR/backend/.venv/bin/python" ] || "$PY" -m venv "$DIR/backend/.venv"
    "$DIR/backend/.venv/bin/pip" install -q -r "$DIR/backend/requirements.txt"
  fi

  # What is running where, for `status` and for promote's staging check.
  if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    tag="$(head_tag)"
    printf '%s %s %s\n' "${tag:-untagged}" "$(head_commit)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DIR/VERSION"
  else
    rm -f "$DIR/VERSION"
  fi

  say "-> service definition"
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$DIR/serve.sh</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SKIP_BUILD</key><string>true</string>
    <key>KEEP_AWAKE</key><string>$KEEP_AWAKE</string>
    <key>INSITE_ENV</key><string>$ENV</string>
    <key>ENV_FILE</key><string>$ENV_FILE</string>
    <key>PORT</key><string>$PORT</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <!-- Restart on crash, and keep retrying while e.g. Docker is still
       starting after login. ThrottleInterval spaces the retries. -->
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$DIR/logs/web.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/web.err.log</string>
</dict>
</plist>
PLISTEOF

  start
}

stage() {
  use_env staging
  require_clean
  deploy_to
}

promote() {
  require_release
  use_env staging
  staged="$(deployed_commit "$DIR")"
  [ -n "$staged" ] || die "staging has no recorded version. Run: ./scripts/live.sh stage"
  [ "$staged" = "$(head_commit)" ] || die "staging is running ${staged:0:8}, this checkout is $(head_commit | cut -c1-8).
   Promote only what was checked on staging: stage this commit first."
  use_env live
  deploy_to
}

rollback() {
  use_env "${1:-live}"
  [ -f "$DIR.prev/VERSION" ] || die "no previous release kept in $DIR.prev"
  say "-> rolling $ENV back to $(awk '{print $1, substr($2,1,8)}' "$DIR.prev/VERSION")"
  rsync -a --delete --exclude 'logs/' "$DIR.prev/" "$DIR/"
  start
}

# verify ENV SHA: the environment answers and runs exactly that commit.
verify() {
  use_env "$1"
  want="$2"
  [ -n "$want" ] || die "usage: live.sh verify live|staging COMMIT_SHA"
  wait_healthy || die "$ENV is not answering on :$PORT"
  got="$(deployed_commit "$DIR")"
  [ "$got" = "$want" ] || die "$ENV runs ${got:0:8}, expected ${want:0:8}"
  say "OK  $ENV runs ${want:0:8} and answers on :$PORT"
}

refresh_staging() {
  use_env staging
  latest="$(ls -t "$BACKUPS"/insite-*.sql.gz.enc 2>/dev/null | head -n 1 || true)"
  [ -n "$latest" ] || die "no backups in $BACKUPS"
  # restore_db.sh is destructive; make sure it can only ever hit staging.
  [ "$DB_EXPECTED" = "insite_staging" ] || die "refusing: target is not insite_staging"
  say "-> restoring $(basename "$latest") into $DB_EXPECTED"
  POSTGRES_DB="$DB_EXPECTED" "$ROOT/scripts/restore_db.sh" "$latest" --yes
  if loaded; then
    say "-> restarting staging so it runs migrations against the fresh copy"
    start
  fi
}

status_one() {
  use_env "$1"
  say "[$ENV]"
  if loaded; then
    pid="$(launchctl print "$DOMAIN/$LABEL" | awk '/^\tpid =/{print $3}')"
    if [ -n "$pid" ]; then say "  service: running (pid $pid)"; else say "  service: installed, not running"; fi
  else
    say "  service: not installed / stopped"
  fi
  if [ -f "$DIR/VERSION" ]; then
    read -r v c t < "$DIR/VERSION"
    say "  version: $v (${c:0:8}, deployed $t)"
  else
    say "  version: unknown (deployed before versioning)"
  fi
  if healthy; then say "  local  :$PORT  answering"; else say "  local  :$PORT  NOT answering"; fi
  code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$URL/api/health" || true)"
  say "  public $URL  HTTP $code"
}

cmd="${1:-}"
target="${2:-}"
case "$cmd" in
  stage)            stage ;;
  promote)          promote ;;
  rollback)         rollback "${target:-live}" ;;
  verify)           verify "${target:-}" "${3:-}" ;;
  deploy)           use_env live; deploy_to ;;
  refresh-staging)  refresh_staging ;;
  status)
    case "${target:-all}" in
      all) status_one live; status_one staging ;;
      *)   status_one "$target" ;;
    esac ;;
  restart) use_env "${target:-live}"; [ -f "$PLIST" ] || die "$ENV not deployed yet"; start ;;
  stop)    use_env "${target:-live}"; loaded && launchctl bootout "$DOMAIN/$LABEL" && say "$ENV stopped" || say "$ENV was not running" ;;
  logs)    use_env "${target:-live}"; exec tail -n 50 -f "$DIR/logs/web.err.log" ;;
  *)       sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

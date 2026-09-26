#!/usr/bin/env bash
# Run the live site as a background service.
#
#   ./scripts/live.sh deploy    build, copy to ~/Insite-Live, (re)start
#   ./scripts/live.sh status    is it running, is it answering
#   ./scripts/live.sh logs      follow the server log (Ctrl+C to stop watching)
#   ./scripts/live.sh restart   restart without redeploying
#   ./scripts/live.sh stop      stop it (stays stopped until deploy/restart)
#
# Why a COPY in ~/Insite-Live instead of running from this folder:
#  * ~/Documents is protected by macOS TCC, and a launchd agent reading from
#    it fails with "Operation not permitted" unless /bin/bash is granted Full
#    Disk Access -- far too broad (same reason as install_backup.sh).
#  * Editing code here no longer changes the live site underneath visitors.
#    The live site changes only when you run `deploy`.
#
# The service starts at login, restarts itself if it crashes, and keeps the
# Mac awake while it runs (while on power, lid open). It serves on
# 127.0.0.1:8080, where the Cloudflare tunnel points.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE="${INSITE_LIVE_DIR:-$HOME/Insite-Live}"
LABEL="com.insite.web"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
PORT=8080
# Real env files live outside ~/Documents (TCC) and outside any checkout, so
# a CI runner's clone deploys with the same secrets. backend/.env and
# backend/.env.production are symlinks here for dev.sh.
SECRETS="${INSITE_SECRETS_DIR:-$HOME/.config/insite}"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

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
  loaded && launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  # bootout returns before the old process has fully released the port.
  for _ in $(seq 1 20); do
    lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.5
  done
  launchctl bootstrap "$DOMAIN" "$PLIST"
  say "-> waiting for the site to answer on :$PORT"
  if wait_healthy; then
    say "OK  live site is up: https://app.mateuszbieda.dev"
  else
    say "!!  not answering after 60s. Last log lines:"
    tail -n 25 "$LIVE/logs/web.err.log" 2>/dev/null || true
    exit 1
  fi
}

deploy() {
  [ -f "$SECRETS/.env" ] || die "$SECRETS/.env missing"
  [ -f "$SECRETS/.env.production" ] || die "$SECRETS/.env.production missing"

  # A foreground serve.sh (Terminal) would hold the port.
  if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 && ! loaded; then
    die "something is already serving on :$PORT -- probably serve.sh in a
Terminal window. Press Ctrl+C there first, then re-run this."
  fi

  say "-> building frontend"
  ( cd "$ROOT/frontend" && npm run build >/dev/null ) || die "frontend build failed"

  say "-> copying app to $LIVE"
  mkdir -p "$LIVE/backend" "$LIVE/frontend" "$LIVE/logs"
  # --delete removes files deleted here; excluded paths (the live venv and
  # secrets) are never touched by it.
  rsync -a --delete \
    --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
    --exclude 'tests/' --exclude '.env*' \
    "$ROOT/backend/" "$LIVE/backend/"
  rsync -a --delete "$ROOT/frontend/dist/" "$LIVE/frontend/dist/"
  install -m 755 "$ROOT/serve.sh" "$LIVE/serve.sh"
  install -m 600 "$SECRETS/.env" "$LIVE/backend/.env"
  install -m 600 "$SECRETS/.env.production" "$LIVE/backend/.env.production"

  say "-> python environment"
  PY="$("$ROOT/backend/.venv/bin/python" -c 'import sys; print(sys._base_executable)')"
  case "$PY" in "$HOME/Documents"*) die "base python lives in ~/Documents ($PY)";; esac
  if command -v uv >/dev/null 2>&1; then
    [ -x "$LIVE/backend/.venv/bin/python" ] || uv venv -q --python "$PY" "$LIVE/backend/.venv"
    uv pip install -q --python "$LIVE/backend/.venv/bin/python" -r "$LIVE/backend/requirements.txt"
  else
    [ -x "$LIVE/backend/.venv/bin/python" ] || "$PY" -m venv "$LIVE/backend/.venv"
    "$LIVE/backend/.venv/bin/pip" install -q -r "$LIVE/backend/requirements.txt"
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
  <array><string>/bin/bash</string><string>$LIVE/serve.sh</string></array>
  <key>WorkingDirectory</key><string>$LIVE</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SKIP_BUILD</key><string>true</string>
    <key>KEEP_AWAKE</key><string>true</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <!-- Restart on crash, and keep retrying while e.g. Docker is still
       starting after login. ThrottleInterval spaces the retries. -->
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LIVE/logs/web.out.log</string>
  <key>StandardErrorPath</key><string>$LIVE/logs/web.err.log</string>
</dict>
</plist>
PLISTEOF

  start
}

status() {
  if loaded; then
    pid="$(launchctl print "$DOMAIN/$LABEL" | awk '/^\tpid =/{print $3}')"
    if [ -n "$pid" ]; then say "service: running (pid $pid)"; else say "service: installed, not running"; fi
  else
    say "service: not installed / stopped"
  fi
  if healthy; then say "local  :$PORT  answering"; else say "local  :$PORT  NOT answering"; fi
  code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' https://app.mateuszbieda.dev/api/health || true)"
  say "public https://app.mateuszbieda.dev  HTTP $code"
}

case "${1:-}" in
  deploy)  deploy ;;
  restart) [ -f "$PLIST" ] || die "not deployed yet: run ./scripts/live.sh deploy"; start ;;
  stop)    loaded && launchctl bootout "$DOMAIN/$LABEL" && say "stopped" || say "was not running" ;;
  status)  status ;;
  logs)    exec tail -n 50 -f "$LIVE/logs/web.err.log" ;;
  *)       sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

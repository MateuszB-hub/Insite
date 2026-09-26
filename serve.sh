#!/usr/bin/env bash
# Run Insite in production mode: one process, one port, built assets.
#
#   ./serve.sh
#
# Differs from dev.sh in ways that matter once the app faces the internet:
#   * serves the BUILT frontend, not Vite's dev server (which ships source
#     and an open hot-reload websocket)
#   * one origin on :8000, so there is a single thing to tunnel
#   * refuses to start with insecure settings unless you force it
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/backend/.venv"
# 8080, NOT 8000: dev.sh's backend owns 8000. The tunnel points here, so a
# shared port would publish the dev server (open registration, insecure
# cookies) whenever dev.sh is running.
PORT="${PORT:-8080}"

cd "$ROOT/backend"
# .env holds shared settings (API keys). The environment's overlay
# (.env.production for live, .env.staging for staging) overrides the ones that
# must differ from local dev: database, public URL, CORS, cookies, email.
# dev.sh never reads an overlay, so localhost keeps working. Python's
# load_dotenv does not override variables already exported here, so these
# values win.
ENV_FILE="${ENV_FILE:-.env.production}"
set -a
[ -f .env ] && . ./.env
[ -f "$ENV_FILE" ] && . "./$ENV_FILE"
set +a

# --- refuse to serve the internet insecurely -----------------------------
fail() { echo "refusing to start: $*" >&2; exit 1; }

if [ "${ALLOW_INSECURE:-}" != "true" ]; then
  [ "${INSECURE_COOKIES:-}" = "true" ] && fail \
    "INSECURE_COOKIES=true sends session cookies without the Secure flag.
   Set INSECURE_COOKIES=false in backend/.env (requires HTTPS in front).
   To run locally anyway: ALLOW_INSECURE=true ./serve.sh"

  case "${APP_BASE_URL:-}" in
    https://*) ;;
    *) fail "APP_BASE_URL must be your https:// URL — password reset links use it." ;;
  esac

  case "${CORS_ORIGINS:-}" in
    *localhost*) fail "CORS_ORIGINS still points at localhost. Set it to your public URL." ;;
  esac

  # Password reset emails would print to this terminal and reach nobody.
  # Staging is the exception, on purpose: its data is a copy of live, so it
  # must never email real users. Its reset links go to the staging log.
  [ "${EMAIL_PROVIDER:-console}" = "console" ] && [ "${INSITE_ENV:-}" != "staging" ] && fail \
    "EMAIL_PROVIDER=console: reset emails would never be delivered.
   Set EMAIL_PROVIDER=smtp and SMTP_* (see backend/.env.example), then
   check with: backend/.venv/bin/python -m app.scripts.send_test_email you@example.com"

  case "${SEARCH_PROVIDER:-mock}" in
    mock) echo "!  SEARCH_PROVIDER=mock: Future of Work reports will use placeholder findings." ;;
  esac
fi

# --- build the frontend --------------------------------------------------
# Always rebuild: a stale dist/ silently serves an old frontend against a
# new backend (e.g. one missing the CSRF header, so every sign-in fails).
# It takes seconds.
# SKIP_BUILD is set by the background service, which runs from a deployed
# copy that has the built dist/ but no node_modules (scripts/live.sh builds
# before copying).
if [ "${SKIP_BUILD:-}" != "true" ]; then
  echo "-> building frontend"
  ( cd "$ROOT/frontend" && npm run build )
fi

echo "-> migrations"
"$VENV/bin/alembic" upgrade head

echo "-> serving on http://127.0.0.1:$PORT  (point your tunnel here)"
# Keep the Mac awake for exactly as long as this process lives. `-w $$`
# watches this PID, which `exec` below hands to uvicorn, so stopping the
# server (Ctrl+C or launchctl) releases the wake lock too.
if [ "${KEEP_AWAKE:-}" = "true" ]; then
  /usr/bin/caffeinate -s -w $$ &
fi

SERVE_STATIC=true exec "$VENV/bin/uvicorn" main:app \
  --host 127.0.0.1 --port "$PORT" --workers 1 --proxy-headers \
  --forwarded-allow-ips '127.0.0.1'

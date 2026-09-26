#!/usr/bin/env bash
# Launch both Insite servers: FastAPI on :8000, Vite on :5173.
# Vite proxies /api -> :8000, so open http://localhost:5173 in the browser.
#
# Kept compatible with the bash 3.2 that ships on macOS (no `wait -n`).
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/backend/.venv"

if [ ! -x "$VENV/bin/uvicorn" ]; then
  echo "error: backend venv missing. Run:" >&2
  echo "  python3 -m venv backend/.venv" >&2
  echo "  backend/.venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "error: frontend deps missing. Run: (cd frontend && npm install)" >&2
  exit 1
fi

# Local models are the default engine; warn (don't fail) if the daemon is down,
# since the backend falls back to the mock provider on its own.
if command -v ollama >/dev/null 2>&1; then
  if ! curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "!  Ollama is installed but not running - local models unavailable."
    echo "   Start it in another shell with: ollama serve"
  fi
else
  echo "!  Ollama not found - the backend will fall back to the mock provider."
fi

# Stable log path so the e2e demos can read server output (the console email
# provider prints reset links there) without guessing a filename.
LOG_FILE="${INSITE_LOG:-/tmp/insite-dev.log}"
: > "$LOG_FILE"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - INT TERM EXIT
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM EXIT

echo "-> backend   http://localhost:8000  (API docs at /docs)"
( cd "$ROOT/backend" && exec "$VENV/bin/uvicorn" main:app --reload --port 8000 ) 2>&1 | tee -a "$LOG_FILE" &
BACKEND_PID=$!

echo "-> frontend  http://localhost:5173"
( cd "$ROOT/frontend" && exec npm run dev ) 2>&1 | tee -a "$LOG_FILE" &
FRONTEND_PID=$!

echo "   (ctrl-c stops both)"

# Exit as soon as either server dies, so a crash is never silently half-up.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

echo "a server exited - shutting the other one down" >&2

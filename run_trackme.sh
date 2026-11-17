#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
UVICORN="$BACKEND_DIR/venv/bin/uvicorn"

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
    printf 'Missing %s/backend/.env. Configure it before launching TRACKME.\n' "$PROJECT_DIR" >&2
    exit 1
fi

if [[ ! -x "$UVICORN" ]]; then
    printf 'Could not find the backend environment at %s.\n' "$BACKEND_DIR/venv" >&2
    exit 1
fi

api_pid=
frontend_pid=

cleanup() {
    if [[ -n "$api_pid" ]]; then
        kill "$api_pid" 2>/dev/null || true
        wait "$api_pid" 2>/dev/null || true
    fi
    if [[ -n "$frontend_pid" ]]; then
        kill "$frontend_pid" 2>/dev/null || true
        wait "$frontend_pid" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf 'Starting TRACKME. Make sure MySQL is running.\n'

(
    cd "$BACKEND_DIR"
    exec "$UVICORN" app.main:app --host 127.0.0.1 --port 8000
) &
api_pid=$!

python3 -m http.server 5500 --bind 127.0.0.1 --directory "$PROJECT_DIR/frontend" &
frontend_pid=$!

sleep 2
if ! kill -0 "$api_pid" 2>/dev/null; then
    printf 'The API failed to start. Check the message above and your backend/.env settings.\n' >&2
    wait "$api_pid" || true
    exit 1
fi
if ! kill -0 "$frontend_pid" 2>/dev/null; then
    printf 'The frontend server failed to start. Check whether port 5500 is already in use.\n' >&2
    wait "$frontend_pid" || true
    exit 1
fi

xdg-open http://127.0.0.1:5500/ >/dev/null 2>&1 || \
    printf 'Could not open a browser automatically. Visit http://127.0.0.1:5500/.\n'
printf 'TRACKME is running. Close this terminal to stop it.\n'

wait "$api_pid"

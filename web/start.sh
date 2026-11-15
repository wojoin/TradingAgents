#!/usr/bin/env bash
# Start the TradingAgents web app: the FastAPI backend and the Vite front end, in the background.
#
#   web/start.sh            backend on 127.0.0.1:8765, front end on http://127.0.0.1:5173
#
# Ports: TA_API_PORT (default 8765), TA_WEB_PORT (default 5173).
# PIDs and logs go to web/.run/; stop both with web/stop.sh.
set -euo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$WEB_DIR")"
RUN_DIR="$WEB_DIR/.run"
API_PORT="${TA_API_PORT:-8765}"
WEB_PORT="${TA_WEB_PORT:-5173}"
mkdir -p "$RUN_DIR"

listening() { lsof -nP -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

running() {   # a pid file whose process is still alive
  [[ -f "$RUN_DIR/$1.pid" ]] && kill -0 "$(cat "$RUN_DIR/$1.pid")" 2>/dev/null
}

wait_for() {  # wait_for <name> <url> <pid>
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "$2" 2>/dev/null; then return 0; fi
    if ! kill -0 "$3" 2>/dev/null; then
      echo "✗ $1 exited; see $RUN_DIR/$1.log"; tail -n 20 "$RUN_DIR/$1.log"; return 1
    fi
    sleep 0.5
  done
  echo "✗ $1 did not answer at $2 within 30s; see $RUN_DIR/$1.log"; return 1
}

# Python: the repository's virtualenv if there is one.
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then PY="$REPO_DIR/.venv/bin/python"; else PY="$(command -v python3)"; fi
if ! "$PY" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "✗ FastAPI/uvicorn are not installed for $PY. Run: pip install -e \".[web,ashare]\" (from $REPO_DIR)"
  exit 1
fi

# ---- backend -----------------------------------------------------------------
if running backend; then
  echo "• backend already running (pid $(cat "$RUN_DIR/backend.pid")) on port $API_PORT"
elif listening "$API_PORT"; then
  echo "✗ port $API_PORT is taken by another process:"; lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN
  echo "  Free it, or start on another port: TA_API_PORT=8766 web/start.sh"; exit 1
else
  cd "$REPO_DIR"
  nohup "$PY" -m uvicorn web.server.app:app --host 127.0.0.1 --port "$API_PORT" \
    >"$RUN_DIR/backend.log" 2>&1 &
  echo $! >"$RUN_DIR/backend.pid"
  wait_for backend "http://127.0.0.1:$API_PORT/api/settings" "$(cat "$RUN_DIR/backend.pid")"
  echo "✓ backend  http://127.0.0.1:$API_PORT  (pid $(cat "$RUN_DIR/backend.pid"), API docs /api/docs)"
fi

# ---- front end ---------------------------------------------------------------
cd "$WEB_DIR/frontend"
if [[ ! -d node_modules ]]; then
  echo "• installing front-end dependencies (npm install) ..."
  npm install --no-fund --no-audit >"$RUN_DIR/npm-install.log" 2>&1 || {
    echo "✗ npm install failed; see $RUN_DIR/npm-install.log"; exit 1; }
fi
if running frontend; then
  echo "• front end already running (pid $(cat "$RUN_DIR/frontend.pid")) on port $WEB_PORT"
elif listening "$WEB_PORT"; then
  echo "✗ port $WEB_PORT is taken by another process:"; lsof -nP -iTCP:"$WEB_PORT" -sTCP:LISTEN
  echo "  Free it, or start on another port: TA_WEB_PORT=5174 web/start.sh"; exit 1
else
  # vite itself, not through npm, so the pid file names the server process.
  TA_API_PORT="$API_PORT" nohup ./node_modules/.bin/vite --host 127.0.0.1 --port "$WEB_PORT" --strictPort \
    >"$RUN_DIR/frontend.log" 2>&1 &
  echo $! >"$RUN_DIR/frontend.pid"
  wait_for frontend "http://127.0.0.1:$WEB_PORT/" "$(cat "$RUN_DIR/frontend.pid")"
  echo "✓ front end http://127.0.0.1:$WEB_PORT  (pid $(cat "$RUN_DIR/frontend.pid"))"
fi

echo
echo "Open http://127.0.0.1:$WEB_PORT   ·   logs: $RUN_DIR   ·   stop: web/stop.sh"

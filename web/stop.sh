#!/usr/bin/env bash
# Stop the TradingAgents web app started by web/start.sh: the front end, then the backend.
#
# Stops the processes named in web/.run/*.pid. A server still holding its port
# (started some other way) is reported, not killed: it may not be this app.
set -uo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$WEB_DIR/.run"
API_PORT="${TA_API_PORT:-8765}"
WEB_PORT="${TA_WEB_PORT:-5173}"

stop() {  # stop <name> <port>
  local name="$1" port="$2" pidfile="$RUN_DIR/$1.pid"
  if [[ -f "$pidfile" ]]; then
    local pid; pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      pkill -TERM -P "$pid" 2>/dev/null   # children first (uvicorn/vite workers)
      kill -TERM "$pid" 2>/dev/null
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
      if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null; echo "✓ $name stopped (forced, pid $pid)"
      else
        echo "✓ $name stopped (pid $pid)"
      fi
    else
      echo "• $name was not running"
    fi
    rm -f "$pidfile"
  else
    echo "• $name: no pid file, nothing started by start.sh"
  fi
  if lsof -nP -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  ! port $port is still in use by a process start.sh did not start (left running):"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN | sed 's/^/    /'
  fi
}

stop frontend "$WEB_PORT"
stop backend "$API_PORT"

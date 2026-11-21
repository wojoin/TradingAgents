#!/usr/bin/env bash
# Restart the TradingAgents web app: stop it (web/stop.sh), then start it (web/start.sh).
#
#   web/restart.sh              backend and front end
#   web/restart.sh --backend    the backend only (the front end reloads code by itself; the
#                               backend keeps the code it started with, so this is the usual one)
#   web/restart.sh --wait       wait for the running analyses to finish first, then restart
#   web/restart.sh --force      restart even while analyses are running (they are lost)
#
# Restarting the backend ends any analysis in progress, so by default it refuses while one is
# running and lists them. A server of this app holding the port without a pid file (started by
# hand) is stopped too; any other process on the port is left alone, as stop.sh does.
# Ports: TA_API_PORT (default 8765), TA_WEB_PORT (default 5173).
set -uo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$WEB_DIR")"
RUN_DIR="$WEB_DIR/.run"
API_PORT="${TA_API_PORT:-8765}"
WEB_PORT="${TA_WEB_PORT:-5173}"
WAIT_POLL=30                     # seconds between checks with --wait

only_backend=0 wait=0 force=0
for arg in "$@"; do
  case "$arg" in
    --backend) only_backend=1 ;;
    --wait) wait=1 ;;
    --force) force=1 ;;
    -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "✗ unknown option: $arg (see web/restart.sh --help)"; exit 2 ;;
  esac
done

running_runs() {  # the analyses in progress, one "id ticker" a line (none when the backend is down)
  curl -fsS --max-time 5 "http://127.0.0.1:$API_PORT/api/runs" 2>/dev/null | python3 -c '
import json, sys
try:
    runs = json.load(sys.stdin)
except ValueError:
    runs = []
for r in runs:
    if r.get("status") in ("queued", "running"):
        print(r.get("id"), r.get("symbol") or r.get("ticker"), r.get("status"), "since", r.get("started") or r.get("created"))
'
}

busy="$(running_runs)"
if [[ -n "$busy" && $force -eq 0 ]]; then
  if [[ $wait -eq 0 ]]; then
    echo "✗ analyses are running; restarting the backend would end them:"
    echo "$busy" | sed 's/^/    /'
    echo "  Wait for them: web/restart.sh --wait   ·   or end them: web/restart.sh --force"
    exit 1
  fi
  echo "• waiting for the running analyses to finish (checking every ${WAIT_POLL}s):"
  echo "$busy" | sed 's/^/    /'
  while [[ -n "$(running_runs)" ]]; do sleep "$WAIT_POLL"; done
  echo "✓ no analysis running"
fi

# A server of this app on the port without a pid file (started by hand): adopt it, so stop.sh
# stops it. Recognised by its command and working directory; anything else is left alone.
adopt() {  # adopt <name> <port> <command pattern> <working directory>
  local pidfile="$RUN_DIR/$1.pid" pid cwd
  pid="$(lsof -nP -tiTCP:"$2" -sTCP:LISTEN 2>/dev/null | head -n 1)"
  [[ -z "$pid" ]] && return
  [[ -f "$pidfile" ]] && [[ "$(cat "$pidfile")" == "$pid" ]] && return
  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
  if ps -o command= -p "$pid" | grep -q -- "$3" && [[ "$cwd" == "$4" ]]; then
    mkdir -p "$RUN_DIR"; echo "$pid" >"$pidfile"
    echo "• $1 on port $2 was started without start.sh (pid $pid): ${5:-stopping it too}"
  fi
}

adopt backend "$API_PORT" "uvicorn web.server.app:app" "$REPO_DIR"
if [[ $only_backend -eq 1 ]]; then
  adopt frontend "$WEB_PORT" "vite" "$WEB_DIR/frontend" "kept running"
  # stop.sh stops both; stop the backend alone with its function.
  TA_API_PORT="$API_PORT" TA_WEB_PORT="$WEB_PORT" bash -c "source <(sed -n '/^stop() {/,/^}/p' '$WEB_DIR/stop.sh'); \
    RUN_DIR='$RUN_DIR'; stop backend '$API_PORT'"
else
  adopt frontend "$WEB_PORT" "vite" "$WEB_DIR/frontend"
  TA_API_PORT="$API_PORT" TA_WEB_PORT="$WEB_PORT" "$WEB_DIR/stop.sh"
fi
echo
TA_API_PORT="$API_PORT" TA_WEB_PORT="$WEB_PORT" exec "$WEB_DIR/start.sh"

# TradingAgents Web

A browser front end for TradingAgents: start an analysis from a stock code, follow
every agent live, browse and sort saved reports, view the daily K-line, and download
reports as Markdown, HTML or a ZIP of the whole report folder.

- `server/`: FastAPI. It runs the same trading graph as the CLI and saves the same
  report tree under `results_dir/reports` (by default `~/.tradingagents/logs/reports`).
- `frontend/`: Vue 3 + Vite + TypeScript, with PrimeVue (tables), TradingView
  Lightweight Charts (K-line) and markdown-it (reports).

## Settings

A web run needs only a stock code (`300308`, `600519.SH`, `AAPL` ...). Everything else
comes from the CLI's last run, remembered in `~/.tradingagents/cli_prefs.json`: provider,
models, research depth, output language and analysts. Run the CLI once to set them; the
API keys come from `.env` as for the CLI. The analysis date is today.

Runs execute one at a time; a second one waits in the queue. Runs started from the web
are listed until the server restarts; their reports stay on disk.

## Run

Install the server's dependencies once, from the repository root:

```bash
pip install -e ".[web,ashare]"        # or: uv pip install -e ".[web,ashare]"
```

### Scripts (both services in the background)

```bash
web/start.sh     # backend on 127.0.0.1:8765, front end on http://127.0.0.1:5173
web/stop.sh      # stops both
```

`start.sh` uses the repository's `.venv` when there is one, runs `npm install` the
first time, waits until both answer, and refuses a port another process holds (it
lists the process). Ports: `TA_API_PORT`, `TA_WEB_PORT`. PIDs and logs are in
`web/.run/`. `stop.sh` stops only what `start.sh` started.

### One process (built front end)

```bash
cd web/frontend && npm install && npm run build && cd ../..
uvicorn web.server.app:app --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765.

### Development (hot reload)

```bash
uvicorn web.server.app:app --host 127.0.0.1 --port 8765 --reload   # terminal 1, repository root
cd web/frontend && npm run dev                                      # terminal 2
```

Open http://localhost:5173; Vite forwards `/api` to port 8765 (set `TA_API_PORT` to change it).

Keep the server on `127.0.0.1`: it has no login, and every run spends model credits.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/settings` | the settings a run will use |
| POST | `/api/runs` | `{"ticker": "300308"}`: queue an analysis for today |
| GET | `/api/runs`, `/api/runs/{id}` | runs, and one run's agents and sections so far |
| GET | `/api/runs/{id}/events` | the run's live events (Server-Sent Events; resumes from `Last-Event-ID`) |
| GET | `/api/reports`, `/api/reports/{id}` | saved reports, and one report's sections |
| GET | `/api/reports/{id}/download?format=md\|html\|zip` | download (`&inline=1` opens the HTML page) |
| GET | `/api/kline/{ticker}?end=YYYY-MM-DD&days=250` | daily bars (AKShare for A-shares, else Yahoo) |

Interactive API docs: http://127.0.0.1:8765/api/docs.

## Learning resources (official, English)

Vue https://vuejs.org/guide/ · Vite https://vite.dev/guide/ · PrimeVue https://primevue.org ·
Lightweight Charts https://tradingview.github.io/lightweight-charts/ · FastAPI https://fastapi.tiangolo.com

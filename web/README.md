# TradingAgents Web

A browser front end for TradingAgents, with a left-hand menu:

- **自选** (watchlist): named, coloured groups (up to 256) along the top; click one to
  list its stocks: code, name, change, price, volume, amount, 5-day change, main-force
  flow, turnover % and P/E (TTM: the latest report period's year to date, plus the last
  annual report, less the same period a year before). Every column sorts; drag a header
  to move its column (order and sort are remembered in the browser). Create, rename,
  recolour and delete groups; add stocks from the box, or with the star in 行情 and 个股,
  which lists the groups to tick. A stock may sit in several groups. The group 默认
  always exists and cannot be deleted, renamed or recoloured. Long-press a row (or right-click it) for a menu:
  分组 (every group, the stock's own in dark, a click adds or removes it), 移到最前 /
  移到最后 (within the group), and 笔记: a note that belongs to the stock, the same in
  every group (marked beside its name). Kept on the server in
  `~/.tradingagents/watchlist.json`; a list from before groups becomes the group 默认.
- **个股** (stock): search by code or name (or click a row in 行情); the stock's latest
  quote, industry and fund flow, its daily K-line since listing (the local store's
  `snapshots/base` history, then the daily cross-sections after it; unadjusted, opening
  on the last year, with 3M / 1Y / 3Y / all ranges), its saved reports, and a button to
  analyse it. Price gaps between adjacent candles (today's low above yesterday's high, or
  today's high below yesterday's low) show as grey bands across the price pane, which a
  checkbox hides; the crosshair shows the date as 2026-11-12.
- **行情** (market): every A-share on any trading day picked from a calendar (weekends and
  holidays disabled), with the day's count of rises, falls and unchanged, from the local
  AKShare store (`.akshare_data/snapshots`; a day before the daily directories is read out
  of `snapshots/base` in a few seconds the first time, then cached under `.akshare_data/web`): code, name, change, price, main-force net inflow, opening
  change, high, low, amount, volume, 5-day change (each session's change compounded, so
  an ex-dividend day does not distort it), Shenwan industry, turnover %, P/E and EPS
  (TTM), market value and shares, total and floating; sortable, searchable, filterable by
  industry, exportable as CSV, with a star to add a stock to 自选. A list at the bottom
  narrows it to 沪深A股, 沪市, 深市 or 京市 A股, 沪深300 (today's constituents, from China
  Securities Index) or ST stocks; the notes on the figures' sources sit beside it.
  Long-press a row (or right-click it) for groups, the note, the stock page and analysis. The flow is Eastmoney's 今日主力净流入 for the latest
  session; when Eastmoney is rate-limited it is 同花顺's net flow, labelled as such.
- **分析** (analysis): start an analysis from a stock code or name (a name resolves to
  its code, and an ambiguous one lists the candidates), follow every agent live, and
  the saved reports in a table below, each downloadable as Markdown, HTML or a ZIP.

- `server/`: FastAPI. It runs the same trading graph as the CLI and saves the same
  report tree under `results_dir/reports` (by default `~/.tradingagents/logs/reports`).
- `frontend/`: Vue 3 + Vite + TypeScript, with PrimeVue (tables), TradingView
  Lightweight Charts (K-line) and markdown-it (reports).

PrimeVue is pinned to 4.5.5, `@primeuix/themes` to 2.0.3 and primeicons to 7.0.0, all
MIT. From PrimeVue 5 and primeicons 8 the packages are commercial ("PrimeUI": a licence
key is required, with a free community licence for eligible users) and show an
"Invalid PrimeUI License" notice without one, so do not upgrade past them without
deciding on that licence.

## Settings

The analysis form offers what the CLI asks before a run: the stock (required; a code
or a name), the analysis date, the analysts, the research depth (1, 3 or 5 debate
rounds), the LLM provider (with its China-region variant, or the endpoint of a local or
custom server), the deep- and quick-thinking models (listed, or any model id), the
provider's reasoning setting (OpenAI, Anthropic, Google) and the report language.

Defaults are the last run's answers in `~/.tradingagents/cli_prefs.json`, shared with
the CLI; a run started on the page saves its answers there. API keys come from `.env`,
as for the CLI: a provider without its key is shown but cannot be picked, and the
server refuses it. ChatGPT-plan, Azure and Bedrock runs need the CLI.

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
| GET | `/api/options` | every option a run can take, with the last run's answers as defaults |
| GET | `/api/market?date=YYYY-MM-DD` | every A-share on the day (latest by default; any trading day) |
| GET | `/api/market/calendar` | the first and last trading day, and the holidays in between |
| GET | `/api/market/index/000300/members` | the CSI 300's constituents today |
| GET | `/api/stocks/search?q=`, `/api/stocks/{code}` | find stocks by code or name; one stock's quote |
| GET | `/api/watchlist` | the groups, and their stocks' rows by code |
| POST, PATCH, DELETE | `/api/watchlist/groups`, `/api/watchlist/groups/{id}` | create, rename / recolour, delete a group |
| PUT, DELETE | `/api/watchlist/groups/{id}/stocks/{code}` | add an A-share to a group, or remove it |
| POST | `/api/watchlist/groups/{id}/stocks/{code}/move` | `{"to": "top"}` or `"bottom"`: move it within the group |
| PUT | `/api/watchlist/notes/{code}` | `{"text"}`: the stock's note, shared by every group (empty deletes it) |
| POST | `/api/runs` | `{"ticker": "300308" or "中际旭创", "options": {...}}`: queue an analysis; options as `/api/options` lists, any left out take the defaults |
| GET | `/api/runs`, `/api/runs/{id}` | runs, and one run's agents and sections so far |
| GET | `/api/runs/{id}/events` | the run's live events (Server-Sent Events; resumes from `Last-Event-ID`) |
| GET | `/api/reports`, `/api/reports/{id}` | saved reports, and one report's sections |
| GET | `/api/reports/{id}/download?format=md\|html\|zip` | download (`&inline=1` opens the HTML page) |
| GET | `/api/kline/{ticker}?source=snapshot` | an A-share's whole daily history from the local store (unadjusted) |
| GET | `/api/kline/{ticker}?end=YYYY-MM-DD&days=250` | the last adjusted daily bars (AKShare for A-shares, else Yahoo) |

Interactive API docs: http://127.0.0.1:8765/api/docs.

## Learning resources (official, English)

Vue https://vuejs.org/guide/ · Vite https://vite.dev/guide/ · PrimeVue https://primevue.org ·
Lightweight Charts https://tradingview.github.io/lightweight-charts/ · FastAPI https://fastapi.tiangolo.com

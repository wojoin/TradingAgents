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
  of `snapshots/base` in a few seconds the first time, then cached under `.akshare_data/web`;
  the calendar runs to the last closed trading day, and a day after the newest snapshot is
  synced in the background when picked — the same as `tradingagents-ashare sync --only snapshots`,
  a couple of minutes when skipped days need each stock's bars — with progress shown): code, name, change, price, main-force net inflow, opening
  change, high, low, amount, volume, 5-day change (each session's change compounded, so
  an ex-dividend day does not distort it), Shenwan 一级 / 二级 / 三级 industry, turnover %, P/E and EPS
  (TTM), market value and shares, total and floating; sortable, searchable, filterable by
  industry (three cascading lists), exportable as CSV, with a star to add a stock to 自选. A list at the bottom
  narrows it to 沪深A股, 沪市, 深市 or 京市 A股, 沪深300 (today's constituents, from China
  Securities Index) or ST stocks; the notes on the figures' sources sit beside it.
  The industries come from 申万's own files kept in `.akshare_data/manual/sw_class/`
  (`StockClassifyUse_stock.xls`, each stock's code, with `SwClassCode_2021.xls` for the names).
  申万's site refuses programs, so the sync button beside the 三级 list opens the file in the
  browser and the server copies it in from ~/Downloads, only when the classification changed
  (what changed is kept in `meta.json`); about once a month. Where those files have no 三级,
  乐咕乐股's copy (`web/sw3/`, built only while 申万's files are missing) fills in, marked 「乐」.
  Long-press a row (or right-click it) for groups, the note, the stock page and analysis. The flow is Eastmoney's 今日主力净流入 for the latest
  session; when Eastmoney is rate-limited it is 同花顺's net flow, labelled as such.
  Below the table, for the day shown: the spread of changes in bands (falls >10%, 10–7, 7–5,
  5–3, 3–0, unchanged, rises 0–3 … >10%); the limit board — limit-ups, limit-downs, 炸板
  (touched the upper limit, closed below) and its rate, and the limit-ups by days in a row
  (连板天梯); and the Shenwan industries ranked (level 1 or 2; a level-1 name filters the
  table). Over the day, 60 trading days, six months or a year to it, each card with its own
  span: rises and falls, limit moves, 赚钱效应 (the median stock's change), the 上证指数,
  沪深300, 中证500, 中证1000, 创业板指, 创业板综, 科创综指 and 科创50 against the median stock with the advance-decline line, and the
  amount traded. Limits follow the boards: main board 10%, ST 5% (10% from 2026-07-06),
  ChiNext and STAR 20%, Beijing 30% (its limit prices cut to the fen, the others round half
  up); a move past the limit is a day without one (a new listing) and is not counted. Base
  days are worked out once, a year at a time, and kept in `.akshare_data/web/`
  (`market_stats_v3.parquet`, `limit_events_v3.parquet`); index closes are kept up to date in
  `.akshare_data/ts/`. The limit-up table adds each stock's shape (一字板 at the limit all day,
  T字板 opened at it, left and came back, else 换手板, from the day's open and low) and, from
  同花顺's limit-up pool (an unpublished JSON feed, years deep, no Beijing exchange), the reason,
  first and last sealing time and the orders left at the limit at the close; Eastmoney's pool
  (about a month deep) fills in the Beijing stocks without a reason. A closed day's details are
  kept in `.akshare_data/web/limit_detail/`; a day neither feed serves shows — and is asked
  again after ten minutes.
  市场广度 opens with 市场广度综合研判 (`server/breadth_verdict.py`): the breadth indicators read in
  three steps (腾落线 and MSI for the trend, MCL, the breadth thrust and ADR for a turn, TRIN and the
  index against 腾落线 to check the move), each state judged by how the 中证全指 did over the next 5
  and 20 days after the same state here (only days whose outcome was known by the day asked
  about), and a short- and medium-term reading built from them; the day's market structure (涨家占比
  / ADL × TRIN_额 / TRIN_量 × MCL: 普涨, 少数股抱团, 抱团瓦解, 无差别下跌 …, each with what followed it; the
  readings day by day in a table, 1 to 60 days or six months, its 项目 column fixed when scrolled);
  what to watch for next;
  below it, that reading on each day of a span (each day judged as it would have been then), what
  the 中证全指 then did, and how often a 偏多 / 偏空 reading was right. The
  中证全指 (`ts/csi_all`) is topped up from Eastmoney, else from 中证指数公司 (Sina's copy stopped in
  2016).
  The stats are laid out by category, the most important first, each in groups: 市场全景
  (今日涨跌, 量能, 资金与风险), 市场广度 Breadth Indicator (趋势: the indexes against 腾落线 ADL, the
  rises and falls, new highs and lows; 动量: MCL, MSI, breadth thrust, ADR / ABI; 参与度与资金: the
  share above MAs, TRIN), 短线情绪 (情绪温度, 涨停板, 主线题材, 情绪指标, 龙虎榜), 板块与风格 (行业表现,
  行业轮动, 概念板块, 风格), 估值 and 业绩; a category folds, remembered in the browser, and the chips
  at the top jump to one.
  Also: the market's breadth and short-term mood (`server/breadth.py`): 涨停溢价
  (yesterday's limit-ups today) and 连板晋级率, 大小盘风格 (the median change of the top 300 /
  301–800 / 801–1800 / smallest 400 by float value, ST left out), 60- and 250-day new highs and
  lows, and the share above the 20- and 60-day MAs, on prices adjusted by compounding each
  day's change. Two years of base are kept in `.akshare_data/web/panel_v3_<base through>.parquet`
  (a few seconds to build once); before the daily snapshots a day's float value is its close
  times the latest float shares.
  Then sectors and valuation (`server/sectors.py`), from 申万宏源研究's official daily
  figures: a heat map of the 31 申万一级 industries' (or the ~130 二级 ones', named 一级-二级 and
  narrowed to one 一级 if wanted; `ts/sw_daily2`) daily change over the last 10 or 20 trading days, each industry's PE, PB and dividend yield with its percentile since 2021, the
  industries' crowding (行业拥挤度: their 5-day turnover share and rate ranked against their own history since 2021), the day's main-force flow summed by industry (latest day only, from the table's rows), and
  申万A指's PE, PB and dividend yield since 2005 with its percentile over a chosen span. The
  series are the data sync's `ts/sw_daily` and `ts/sw_market`, topped up here at most once a
  closed trading day; when 申万 is down the copy on disk is used and the card says so.
  More (`server/extras.py`): 两融余额 for Shanghai and Shenzhen (the data sync's
  `margin_sh` / `margin_sz` history, topped up from the exchanges; a day is published the next
  morning), the 10-year bond yield (`ts/bond`) that gives 股债性价比 (100 / PE less the yield),
  and the limit-ups' themes (同花顺's 涨停原因 split at "+") counted over 3, 5 or 10 days.
  空间板高度 (the highest run of limit-ups) comes with the breadth figures.
  Also from `server/extras.py`: QVIX (the 50ETF volatility index, the data sync's `qvix`), the
  market's main-force flow (Eastmoney, the last 120 trading days), main-force flow by 申万
  industry over 1, 5 or 10 days (Eastmoney's per-stock rankings, latest day only), the shares
  coming off lock-up in the next 30 days, and the day's 龙虎榜 with the institutions' buying
  (kept in `.akshare_data/web/lhb/` once the day is closed); a row opens on the stock's top five
  buying and selling seats (kept with the analysts' copy in `sentiment/lhb_seats/`). 情绪综合分 (`server/breadth.py`)
  averages six short-term readings put on 0–100.
  Also: 分板块表现 (主板 / 创业板 / 科创板 / 北交所: the day's counts, median change, limit moves and
  amount, and each board's median change over time), 成交集中度 (the 100 busiest stocks' and the
  busiest 5%'s share of the amount traded; the panel keeps the amount, so it is `panel_v2`),
  TRIN (the Arms index, by amount TRIN_额 and by volume TRIN_量, with 10-day averages and their
  percentile over 250 days; the panel keeps the volume too, so it is `panel_v3`), the McClellan
  oscillator (ratio-adjusted) and the summation index MSI (as 19 × EMA39 − 9 × EMA19, the sum from the
  start of time, so its zero line does not depend on the first day kept; with its zero crossings), Zweig's breadth thrust (with its signals), the
  advance-decline ratio and absolute breadth index, the share above the 250-day MA,
  涨家 / 涨额 / 涨量占比 with 额价差 and 量价差 (the rising stocks' share of the money less their share
  of the stocks, TRIN's linear cousin), 净新高 as a % of the stocks traded, MCL also on the raw
  count (the classic definition), 放量 / 缩量 against the 5 and 20 days before,
  概念板块热度 (同花顺's concept boards over 1, 5 or 10 days, latest day only; a row opens on the
  board's stocks, from Eastmoney's board of the same name (Sina's when Eastmoney fails or has none), kept in `.akshare_data/web/concepts/` and
  re-checked after 30 days, with what was added and removed; `python -m web.server.daily` re-checks
  up to 40 due boards a run) and 业绩预告 (a
  report period's forecasts, one a stock, by type and 申万 industry, from the events module's
  cache), the last in a sixth category, 业绩.
- **宽基ETF** (broad-based ETFs): the shares of the 20 main broad-based ETFs the "national team"
  holds (沪深300, 上证50, 中证500/800/1000, 创业板, 科创50, 深证100, 上证180 and 金融 funds). Their volume
  can be traded back and forth to itself, so it says little; their shares only move when units are
  created or redeemed, which is where the big money shows. Three charts over the same days: the 20's
  total daily share change in 亿份 (raw, noisy; the day's three biggest movers named under it), the
  加仓指数 (total shares ÷ the total on the base day × 100, base 2025-11-20 by default and any day can
  be picked; the same as each fund's own share index weighted by its part of the base day's total) with 较前日 in a box over the hovered day and
  bands at 70 (above: the bottom is near) and 30 (below: cut positions), and its rate, the index's
  change over 5 and 20 trading days. A card spells out the formulas with the latest day worked through.
  The 20 (the reference video's list of 19 shows rows 2-20, but its charts hold 159922 中证500ETF嘉实 too)
  reproduce its charts to the digit: 2026-01-28 −329.48亿份, 2026-11-03 +196.98亿份, 2026-06-12 30.07 and +0.06. The sentiment analyst reads it too (block 2, 市场情绪:
  `tradingagents/dataflows/broad_etf.py`, never past the analysis date): the index, 较前日, where it sits
  against the bands, the 5 / 20-day rates, the day's biggest movers and the last 10 days. Below, each fund's shares, its change on the day and since the base, and its
  weight. The shares come from the exchanges (上交所 a day for every fund per request, 深交所 a fund
  a month at a time), kept in `.akshare_data/web/etf_shares.parquet` from 2025-10-09 and topped up
  with the missing days on each visit (the first download takes about a minute). A day either
  exchange has not published yet is left out rather than counted as zero, and asked for again after
  half an hour.
- **分析** (analysis): start an analysis from a stock code or name (a name resolves to
  its code, and an ambiguous one lists the candidates), follow every agent live, and
  the saved reports in a table below, each downloadable as Markdown, HTML or a ZIP.
- **指标说明** (guide): what the terms on these pages mean and how to read them (the market
  table, limit moves, the market stats, the industry board, the K-line indicators, the
  analysis options), by section, with a search. The text lives in `views/GuideView.vue`;
  keep it in step when a page changes how it works a figure out.

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
web/restart.sh   # stop, then start (--backend: the backend only; --wait / --force: see below)
```

`start.sh` uses the repository's `.venv` when there is one, runs `npm install` the
first time, waits until both answer, and refuses a port another process holds (it
lists the process). Ports: `TA_API_PORT`, `TA_WEB_PORT`. PIDs and logs are in
`web/.run/`. `stop.sh` stops only what `start.sh` started.

`restart.sh` is the way to load changed backend code (the backend keeps the code it started
with; the front end reloads by itself, so `--backend` is usually enough). Restarting the backend
ends any analysis in progress, so it refuses while one is running and lists them: `--wait`
waits for them to finish and then restarts, `--force` restarts anyway. A server of this app
on the port without a pid file (started by hand) is recognised by its command and directory
and restarted too; any other process on the port is left alone.

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

## Download by hand

The 行情 page syncs the day it opens on when that day is not on disk yet. To fetch ahead of
time, run

```bash
.venv/bin/python -m web.server.daily
```

It brings the daily snapshots up to the last closed trading day (a trading day counts once it
is past 15:30 Beijing time) and fetches once everything the 行情 stats read, so the page opens
without waiting: through the web server when it is up (its own sync, then each stats endpoint),
otherwise in its own process. What cannot be had yet (the 龙虎榜 before about 18:00, a feed
that is down) is listed; run it again later for those. Log (Beijing time):
`.akshare_data/web/daily.log`.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/options` | every option a run can take, with the last run's answers as defaults |
| GET | `/api/market?date=YYYY-MM-DD` | every A-share on the day (latest by default; any trading day) |
| GET | `/api/market/calendar` | the first and last (closed) trading day, the holidays in between, and the days not synced yet |
| GET | `/api/market/stats` | `?range=1d\|60d\|6m\|1y&end=`: rises, falls, unchanged and amount traded, day by day |
| GET | `/api/market/sectors` | `?days=10\|20&level=sw1\|sw2&end=`: 申万一级 industries' heat map and valuation percentiles |
| GET | `/api/market/crowding` | `?end=`: 行业拥挤度 |
| GET | `/api/market/valuation` | `?end=`: 申万A指's PE, PB and dividend yield since 2005 |
| GET | `/api/market/margin` | `?range=&end=`: 两融余额 (Shanghai + Shenzhen) each trading day |
| GET | `/api/market/themes` | `?days=3\|5\|10&date=`: the limit-ups' themes by day |
| GET | `/api/market/qvix` | `?range=&end=`: QVIX, China's VIX |
| GET | `/api/market/flow` | `?range=&end=`: the market's main-force flow |
| GET | `/api/market/flow/industry` | `?span=1d\|5d\|10d&date=`: main-force flow by 申万 industry |
| GET | `/api/market/releases` | `?date=`: lock-up expiries in the next 30 days |
| GET | `/api/market/lhb` | `?date=`: the day's 龙虎榜 |
| GET | `/api/market/lhb/{code}` | `?date=`: that stock's top five buying and selling seats |
| GET | `/api/market/boards` | `?date=`: the day's boards |
| GET | `/api/market/concepts` | `?span=1d\|5d\|10d&date=`: 同花顺's concept boards |
| GET | `/api/market/concepts/{name}/stocks` | `?date=`: a concept's stocks |
| GET | `/api/market/forecasts` | `?date=&period=`: a report period's 业绩预告 |
| GET | `/api/market/breadth/verdict` | `?date=`: 市场广度综合研判 |
| DELETE | `/api/reports/{id}` | delete a report (moved to `reports/.trash/`, recoverable) |
| GET | `/api/stock/{code}/rebound` | 超跌反转 buy signals with their trades (盈 +30% / 止 −15% / 期 20 days / 卖), the ★ 单笔最优 trades (+25% / −30% / 250 days), sell / avoid signals |
| GET | `/api/stock/{code}/flow` | main-force net inflow by day (Eastmoney's ~120 days, kept and grown in `web/flow/`, plus the snapshots' `main_flow`) |
| GET | `/api/stock/{code}/intraday` | `?days=1..5`: minute bars (Sina, 1 minute), for 分时 and 五日 |
| GET | `/api/stock/{code}/ticks` | the day's trades (3-second snapshots; Eastmoney, else Sina; a closed day kept in `web/ticks/`); the 09:25 / 15:00 call auctions marked 竞价 |
| GET | `/api/stock/{code}/auction` | the opening call auction 09:15–09:25 (Eastmoney's pre-market minutes, kept in `web/auction/`), ending on the real 09:25 match |
| GET | `/api/market/sw-class` | 申万行业分类文件 (`.akshare_data/manual/sw_class/`): data date, last checked / changed |
| POST | `/api/market/sw-class/import` | `?since=`: copy the `StockClassifyUse_stock.xls` the browser saved to ~/Downloads, when it differs |
| GET / POST | `/api/market/sw3` | 乐咕乐股's 三级 set (the fallback): its state / download it now |
| GET | `/api/market/breadth/structure` | `?range=1d\|10d\|30d\|60d\|6m&end=`: 当日市场结构 day by day |
| GET | `/api/market/breadth/verdict/history` | `?range=&end=`: that reading day by day, and its hit rate |
| GET | `/api/market/breadth` | `?range=&end=`: 涨停溢价 and 晋级率, size styles, new highs and lows, share above MAs |
| GET | `/api/market/limits` | `?date=`: limit-ups by days in a row (with shape, reason, sealing times, orders), 炸板 and limit-downs |
| GET / POST | `/api/market/sync` | the background snapshot sync: its status and progress, or start it |
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

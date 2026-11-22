# 宽基ETF (broad-based ETF share tracker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 宽基ETF menu in the web app that tracks the daily shares of the 19 broad-based ETFs held by the
"national team", drawing the raw daily change, the 加仓指数 (total shares ÷ total on a base day × 100) and its
rate of change, with a per-fund table.

**Architecture:** One backend module `web/server/etf_flow.py` fetches shares from the two exchanges (SSE: every
fund for one day per request; SZSE: one fund over one month per request), keeps them in
`.akshare_data/web/etf_shares.parquet`, tops the file up with missing days, and computes the series.
`GET /api/etf/broad` serves it. A new Vue view `EtfView.vue` draws three charts with the existing
`LineChart.vue` and a table.

**Tech Stack:** FastAPI, pandas, requests; Vue 3 + PrimeVue + lightweight-charts; pytest.

## Findings this plan rests on (verified 2026-11-21)

- The raw "份额变化" chart in the video is the **sum of daily share changes over the 19 funds** (01-28: video
  −329.48亿份, ours −322.64; 11-03: video +196.98, ours +196.61), not one fund.
- The 加仓指数 is `100 × Σshares(t) / Σshares(base)`, base 2025-12-31 (06-12: video 30.07 / +0.06, ours
  29.85 / +0.05; low ≈ 21.6–22.8 early July; 11-20 ≈ 65.6). Weighting by each fund's own shares is what makes
  this a weighted index: `Σ w_i · s_i(t)/s_i(0)` with `w_i = s_i(0)/Σs(0)`.
- SSE: `https://query.sse.com.cn/commonQuery.do`, sqlId `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L`,
  `STAT_DATE=YYYY-MM-DD`, `TOT_VOL` in 万份; an unpublished day returns an empty `result`.
- SZSE: `https://fund.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=fund_jjgm&TABKEY=tab1&txtDm=<code>&txtStart=&txtEnd=&PAGENO=`,
  `current_size` in 万份 with thousands commas, 20 rows a page; a span of a year returns nothing, a month works.

## Files

- Create `web/server/etf_flow.py`: the fund list, the two fetchers, the cache top-up, the computation, `broad()`.
- Modify `web/server/app.py`: route `GET /api/etf/broad`, docstring line.
- Create `tests/test_etf_flow.py`: computation, top-up with fake fetchers, the real-data regression, the route.
- Modify `web/frontend/src/api.ts`: `EtfBroad` types and `api.etfBroad()`.
- Create `web/frontend/src/views/EtfView.vue`: the page.
- Modify `web/frontend/src/router.ts`, `web/frontend/src/App.vue`: the route and the menu item.
- Modify `web/README.md`: a 宽基ETF paragraph.

### Task 1: the computation (TDD)

- [ ] Test `compute(wide, base)` on a 2-fund, 4-day frame: `change` = Δ total in 亿份 (first day `None`),
      `index` = 100 at base, `rate5`/`rate20` = index − index n days back (`None` before).
- [ ] Test the regression on real shares for 2025-12-31, 2026-01-27/28, 2026-06-11/12 (19 funds, embedded):
      01-28 change ≈ −322.64, 06-12 index ≈ 29.85, its change on the day ≈ +0.05.
- [ ] Test a base day that is not a trading day in the data: the last day on or before it is used; a base before
      the data raises `ValueError`.
- [ ] Implement `compute()` in `etf_flow.py`; run `pytest tests/test_etf_flow.py -q`.

### Task 2: fetchers and cache top-up (TDD)

- [ ] Test `update(days, fetch_sse=, fetch_szse=)` with fakes: an empty cache fetches every day; a second call
      fetches nothing; a day missing from one exchange is left out of the result (never zero-filled) and fetched
      again next time; a fetcher raising leaves what was on disk and reports `stale`.
- [ ] Implement `fetch_sse(day)`, `fetch_szse(code, start, end)` (month chunks, pages), `update()`
      writing `.akshare_data/web/etf_shares.parquet` (long: date, code, shares); retry an unpublished last day
      at most every 30 minutes in-process.

### Task 3: `broad()` and the route

- [ ] `broad(base="2025-12-31", rng="1y")`: rng in `6m|1y|all`; returns `{base, as_of, source, note, funds:[{code,name,exchange,shares,day,since_base,since_base_pct,weight}], days:[{date,total,change,index,rate5,rate20,top:[[code,change]...]}]}`;
      `top` = the three funds with the largest absolute change that day.
- [ ] Route `GET /api/etf/broad?base=YYYY-MM-DD&range=` via `_guard`; test with a monkeypatched `broad`.

### Task 4: front end

- [ ] `api.ts`: types and `etfBroad(base, range)`.
- [ ] `EtfView.vue`: header (as of, source note, base date input, range buttons), three `LineChart`s
      (bars red ≥ 0 / green < 0 for daily change; index line with a 100 level; rate5 / rate20 lines with a 0 level),
      a legend line naming the day's top movers, the 19-fund table (sortable).
- [ ] Router `/etf`, menu item 宽基ETF (`pi pi-chart-line`) between 行情 and 分析.
- [ ] `npm run build` (vue-tsc) passes.

### Task 5: verify and commit

- [ ] Full `pytest tests/test_etf_flow.py tests/test_web_server.py -q`.
- [ ] Start the server, call `/api/etf/broad`, check 01-28 and 06-12 against the findings; open the page.
- [ ] README paragraph; commit.

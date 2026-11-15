"""A-share sentiment inputs for the sentiment analyst, from AKShare.

Three blocks, each a text section the analyst reads:

  资金情绪 (fund sentiment)   ``get_fund_sentiment``
    - 个股资金流: main-force and extra-large-order net inflow per day (Eastmoney)
    - 融资融券: financing balance and short-sale volume per day (SSE / SZSE / BSE detail)
    - 北向资金: Stock Connect holdings per day (Eastmoney)
    - 龙虎榜: listings in the window, with institution / Connect / brokerage-seat net buying
  市场情绪 (market sentiment) ``get_market_sentiment``
    - 涨停池, 炸板池, 跌停池, 昨日涨停池 per day: limit-up count, broken-board rate,
      consecutive-board height and ladder, yesterday's limit-ups' return today
  人气 (popularity)           ``get_popularity``
    - 东财人气排名 and its new / loyal fan split
    - 千股千评: composite score, user-attention index, participation desire

Point in time: no row dated after the trade date is served. Margin detail for day T
is published the next morning, so a run on T reads margin through T-1. LHB's
after-listing returns and seat success rates are never read: they are computed
with later prices.

Feeds that keep only recent history (fund flow ~120 trading days, limit-up pools
~30, popularity ~1 year, 千股千评 ~30 days) report a date they cannot reach as
unobserved, never as an absence. Per-date market tables are cached for good once
the day has closed, so their history accumulates locally over time.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import pandas as pd

from tradingagents.dataflows.symbols import exchange_prefix, normalize_symbol
from tradingagents.dataflows.vendors.akshare import store
from tradingagents.dataflows.vendors.akshare.prices import require_code

FLOW_DAYS = 10      # trading days of fund flow shown
MARGIN_DAYS = 6     # trading days of margin detail read (before the trade date)
NORTH_DAYS = 10     # trading days of northbound holdings shown
LHB_DAYS = 10       # trading days searched for 龙虎榜 listings
LHB_LISTINGS = 3    # most recent listings detailed by seat
MARKET_DAYS = 5     # trading days of market-wide limit-up statistics
POP_DAYS = 7        # rows of popularity shown
NORTH_STALE_DAYS = 10  # calendar days after which the last northbound row is not "current"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _trade_days(end_date: str, n: int, *, before: bool = False) -> list[pd.Timestamp]:
    """The last ``n`` trading days up to ``end_date`` (strictly before it with ``before``)."""
    cal = store.trade_calendar()
    end = pd.Timestamp(end_date)
    days = cal[cal < end] if before else cal[cal <= end]
    return list(days[-n:])


def _closed(day: pd.Timestamp) -> bool:
    """Whether ``day``'s session has closed, so its end-of-day tables are final."""
    return day.date() <= store.last_closed_trade_date()


def _dated(kind: str, key: str, final: bool, fetch: Callable[[], pd.DataFrame], what: str,
           retries: int = 0) -> pd.DataFrame:
    """A per-date table, cached for good under sentiment/<kind>/<key>.pkl once ``final``.

    An empty result is never cached: it can mean "not yet published" as well as "none".
    ``retries`` is for the exchanges' sites, which drop the odd request; Eastmoney is
    never retried, since repeating a rate-limited request extends the block.
    """
    path = store.root() / "sentiment" / kind / f"{key}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    for attempt in range(retries + 1):
        try:
            df = store.call(fetch, what)
            break
        except Exception:
            if attempt == retries:
                raise
            time.sleep(1.0 + attempt)
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if final and len(df):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(path)
    return df


def _per_stock(kind: str, code: str, fetch: Callable[[], pd.DataFrame], what: str) -> pd.DataFrame:
    """A per-stock history, downloaded at most once a day (refreshed intraday)."""
    def get():
        df = store.call(fetch, what)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return store.symbol_cache(kind, code, get, live=True)


def _upto(df: pd.DataFrame, col: str, end_date: str) -> pd.DataFrame:
    """Rows dated on or before ``end_date``, oldest first, with a parsed ``_d`` date column."""
    if df is None or df.empty or col not in df:
        return pd.DataFrame(columns=[*(df.columns if df is not None else []), "_d"])
    out = df.copy()
    out["_d"] = pd.to_datetime(out[col].astype(str), errors="coerce", format="mixed").dt.normalize()
    out = out.dropna(subset=["_d"])
    return out[out["_d"] <= pd.Timestamp(end_date)].sort_values("_d")


def _num(x) -> float:
    v = pd.to_numeric(x, errors="coerce")
    return float("nan") if pd.isna(v) else float(v)


def _yi(x, signed: bool = True) -> str:
    """Yuan as 亿元."""
    v = _num(x)
    return "—" if pd.isna(v) else (f"{v / 1e8:+.2f}亿" if signed else f"{v / 1e8:.2f}亿")


def _wan(x, signed: bool = False) -> str:
    """A count (shares) as 万."""
    v = _num(x)
    return "—" if pd.isna(v) else (f"{v / 1e4:+,.1f}万" if signed else f"{v / 1e4:,.1f}万")


def _pct(x, signed: bool = True, digits: int = 2) -> str:
    v = _num(x)
    return "—" if pd.isna(v) else (f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%")


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def _unavailable(source: str, reason: str) -> str:
    return f"<{source} unavailable: {reason}>\n"


def _section(title: str, source: str, build: Callable[[], str]) -> str:
    """One subsection; any failure becomes an explicit placeholder, never an exception."""
    try:
        body = build()
    except Exception as e:  # noqa: BLE001 — the analyst must always get a block
        body = _unavailable(source, f"{type(e).__name__}: {str(e)[:160]}")
    return f"### {title}\n{body}\n"


# ---------------------------------------------------------------------------
# 资金情绪: 个股资金流
# ---------------------------------------------------------------------------
def _fund_flow(code: str, end_date: str) -> str:
    market = exchange_prefix(code).lower()
    raw = _per_stock("fund_flow", code,
                     lambda: store.ak().stock_individual_fund_flow(stock=code, market=market),
                     "Eastmoney fund flow")
    if raw.empty:
        return _unavailable("Eastmoney fund flow", "the feed returned no rows")
    earliest = pd.to_datetime(raw["日期"], errors="coerce").min()
    df = _upto(raw, "日期", end_date)
    if df.empty:
        return _unavailable("Eastmoney fund flow",
                            f"the feed keeps only recent trading days (from {earliest:%Y-%m-%d}), "
                            f"so {end_date} is unobserved, not an absence of flows")
    main = pd.to_numeric(df["主力净流入-净额"], errors="coerce")
    xl = pd.to_numeric(df["超大单净流入-净额"], errors="coerce")
    small = pd.to_numeric(df["小单净流入-净额"], errors="coerce")
    last = df.tail(FLOW_DAYS)
    rows = [[f"{r['_d']:%Y-%m-%d}", f"{_num(r['收盘价']):.2f}", _pct(r["涨跌幅"]),
             _yi(r["主力净流入-净额"]), _pct(r["主力净流入-净占比"]),
             _yi(r["超大单净流入-净额"]), _pct(r["超大单净流入-净占比"]),
             _yi(r["大单净流入-净额"]), _yi(r["小单净流入-净额"])]
            for _, r in last.iterrows()]
    out = _table(["日期", "收盘", "涨跌幅", "主力净流入", "主力净占比", "超大单净流入", "超大单净占比",
                  "大单净流入", "小单净流入"], rows)

    def total(s, n):
        return _yi(s.tail(n).sum()) if len(s) >= n else f"— (only {len(s)} days)"
    streak, sign = 0, (main.iloc[-1] > 0)
    for v in reversed(main.tolist()):
        if pd.isna(v) or (v > 0) != sign:
            break
        streak += 1
    inflow_days = int((main.tail(FLOW_DAYS) > 0).sum())
    out += (f"\n- 主力净流入合计: 5日 {total(main, 5)}, 10日 {total(main, 10)}, 20日 {total(main, 20)}\n"
            f"- 超大单净流入合计: 5日 {total(xl, 5)}, 10日 {total(xl, 10)}\n"
            f"- 小单 (散户) 净流入合计: 5日 {total(small, 5)}, 10日 {total(small, 10)}\n"
            f"- 近{min(FLOW_DAYS, len(main))}日主力净流入天数: {inflow_days}; "
            f"截至 {df['_d'].iloc[-1]:%Y-%m-%d} 主力连续净{'流入' if sign else '流出'} {streak} 日\n"
            "- Order-size buckets are Eastmoney's estimate from tick sizes (超大单 ≥ 100万元 or 50万股), "
            "not account identities.\n")
    if len(df) < FLOW_DAYS:
        out += f"- Coverage: the feed starts {earliest:%Y-%m-%d}; fewer than {FLOW_DAYS} days precede {end_date}.\n"
    return out


# ---------------------------------------------------------------------------
# 资金情绪: 融资融券
# ---------------------------------------------------------------------------
_MARGIN_SOURCES = {
    "SH": ("stock_margin_detail_sse", "标的证券代码", "SSE"),
    "SZ": ("stock_margin_detail_szse", "证券代码", "SZSE"),
    "BJ": ("stock_margin_detail_bse", "证券代码", "BSE"),
}


def _margin(code: str, end_date: str) -> str:
    exchange = exchange_prefix(code)
    fn, code_col, name = _MARGIN_SOURCES[exchange]
    rows, unpublished, absent = [], [], 0
    for day in _trade_days(end_date, MARGIN_DAYS, before=True):
        key = f"{day:%Y%m%d}"
        try:
            table = _dated(f"margin_{exchange}", key, _closed(day),
                           lambda key=key: getattr(store.ak(), fn)(date=key), f"{name} margin detail",
                           retries=1)
        except Exception:  # noqa: BLE001 — one missing day must not hide the others
            table = pd.DataFrame()
        if table.empty or code_col not in table:
            unpublished.append(f"{day:%Y-%m-%d}")
            continue
        hit = table[table[code_col].astype(str).str.zfill(6) == code]
        if hit.empty:
            absent += 1
            continue
        r = hit.iloc[0]
        rows.append({"d": day, "fin_bal": _num(r.get("融资余额")), "fin_buy": _num(r.get("融资买入额")),
                     "short_vol": _num(r.get("融券余量")), "short_sell": _num(r.get("融券卖出量"))})
    note = (f"Margin detail for a day is published the next morning, so this {end_date} run reads "
            f"margin through the previous trading day.\n")
    if not rows:
        if absent and not unpublished:
            return (f"{normalize_symbol(code)} is not in the {name} margin-trading list (两融标的) on the "
                    f"last {absent} trading days before {end_date}: no financing or short-selling flows exist.\n")
        return _unavailable(f"{name} margin detail",
                            f"no table for {', '.join(unpublished) or 'the window'} (not published or not reachable)") + note
    table_rows = [[f"{x['d']:%Y-%m-%d}", _yi(x["fin_bal"], signed=False), _yi(x["fin_buy"], signed=False),
                   _wan(x["short_vol"]), _wan(x["short_sell"])] for x in rows]
    out = _table(["日期", "融资余额", "融资买入额", "融券余量(股)", "融券卖出量(股)"], table_rows)
    first, last = rows[0], rows[-1]
    if len(rows) > 1 and first["fin_bal"]:
        chg = last["fin_bal"] - first["fin_bal"]
        out += (f"\n- 融资余额 {first['d']:%m-%d}→{last['d']:%m-%d}: {_yi(chg)} "
                f"({_pct(chg / first['fin_bal'] * 100)})\n"
                f"- 融券余量 {first['d']:%m-%d}→{last['d']:%m-%d}: "
                f"{_wan(last['short_vol'] - first['short_vol'], signed=True)}股\n")
    if unpublished:
        out += f"- Missing days (not published or not reachable): {', '.join(unpublished)}\n"
    return out + "- " + note


# ---------------------------------------------------------------------------
# 资金情绪: 北向资金
# ---------------------------------------------------------------------------
def _northbound(code: str, end_date: str) -> str:
    raw = _per_stock("hsgt", code, lambda: store.ak().stock_hsgt_individual_em(symbol=code),
                     "Eastmoney northbound holdings")
    df = _upto(raw, "持股日期", end_date)
    if df.empty:
        return (f"No Stock Connect (北向) holding record for {normalize_symbol(code)} on or before {end_date}: "
                "the stock may not be a Connect target, or the feed does not reach that date.\n")
    last = df.iloc[-1]
    if (pd.Timestamp(end_date) - last["_d"]).days > NORTH_STALE_DAYS:
        return (f"Daily northbound holdings stop at {last['_d']:%Y-%m-%d} (HKEX ended daily disclosure of "
                f"Stock Connect holdings in August 2024), so holdings on {end_date} are unobserved, not "
                f"unchanged. Last known: {_wan(last['持股数量'])}股, {_pct(last['持股数量占A股百分比'], signed=False)} "
                "of A shares. Do not infer current northbound positioning from it.\n")
    tail = df.tail(NORTH_DAYS)
    rows = [[f"{r['_d']:%Y-%m-%d}", _wan(r["持股数量"]), _pct(r["持股数量占A股百分比"], signed=False),
             _wan(r["今日增持股数"], signed=True), _yi(r["今日增持资金"])] for _, r in tail.iterrows()]
    out = _table(["日期", "持股数量(股)", "占A股比例", "当日增持(股)", "当日增持资金"], rows)
    share = pd.to_numeric(tail["持股数量占A股百分比"], errors="coerce")
    flow = pd.to_numeric(tail["今日增持资金"], errors="coerce")
    out += (f"\n- 持股占比 {tail['_d'].iloc[0]:%m-%d}→{tail['_d'].iloc[-1]:%m-%d}: "
            f"{_pct(share.iloc[-1] - share.iloc[0])} (percentage points); 增持资金合计 {_yi(flow.sum())}\n")
    return out


# ---------------------------------------------------------------------------
# 资金情绪: 龙虎榜
# ---------------------------------------------------------------------------
def _seat_kind(name: str) -> str:
    if "机构专用" in name:
        return "机构专用"
    if "沪股通" in name or "深股通" in name:
        return "北向专用席位"
    return "营业部 (游资/散户)"


def _lhb(code: str, end_date: str) -> str:
    days = _trade_days(end_date, LHB_DAYS)
    if not days:
        return _unavailable("Eastmoney 龙虎榜", "no trading days in the window")
    start = days[0]
    listed = _per_stock("lhb_dates", code, lambda: store.ak().stock_lhb_stock_detail_date_em(symbol=code),
                        "Eastmoney 龙虎榜 dates")
    hits = _upto(listed, "交易日", end_date)
    hits = hits[hits["_d"] >= start]
    if hits.empty:
        return (f"No 龙虎榜 listing for {normalize_symbol(code)} from {start:%Y-%m-%d} to {end_date}. "
                "A stock is listed only after an abnormal move (price deviation, turnover, etc.), so no "
                "listing is the normal state, not a signal.\n")
    out = f"{len(hits)} listing day(s) from {start:%Y-%m-%d} to {end_date}; the latest {LHB_LISTINGS} by seat:\n\n"
    for day in sorted(set(hits["_d"]))[-LHB_LISTINGS:]:
        key = f"{day:%Y%m%d}"
        seats = []
        for flag in ("买入", "卖出"):
            t = _dated("lhb_seats", f"{code}_{key}_{flag}", _closed(day),
                       lambda flag=flag, key=key: store.ak().stock_lhb_stock_detail_em(symbol=code, date=key, flag=flag),
                       "Eastmoney 龙虎榜 seats")
            if not t.empty:
                seats.append(t)
        if not seats:
            out += f"**{day:%Y-%m-%d}**: seat detail unavailable\n\n"
            continue
        s = pd.concat(seats, ignore_index=True)
        s = s.drop_duplicates(["交易营业部名称", "买入金额", "卖出金额"])
        s["净额"] = pd.to_numeric(s["买入金额"], errors="coerce") - pd.to_numeric(s["卖出金额"], errors="coerce")
        s["kind"] = s["交易营业部名称"].astype(str).map(_seat_kind)
        reasons = "; ".join(sorted(set(s["类型"].dropna().astype(str)))) if "类型" in s else ""
        by_kind = s.groupby("kind")["净额"].agg(["sum", "count"])
        out += f"**{day:%Y-%m-%d}** — 上榜原因: {reasons or '—'}; 上榜席位净买入合计 {_yi(s['净额'].sum())}\n"
        out += "".join(f"- {k}: {int(r['count'])} 席, 净买入 {_yi(r['sum'])}\n" for k, r in by_kind.iterrows())
        brokers = s[s["kind"] == "营业部 (游资/散户)"]
        brokers = brokers.loc[brokers["净额"].abs().sort_values(ascending=False).index].head(3)
        if len(brokers):
            out += "- 净额最大的营业部: " + "; ".join(
                f"{r['交易营业部名称']} {_yi(r['净额'])}" for _, r in brokers.iterrows()) + "\n"
        out += "\n"
    return out


def get_fund_sentiment(ticker: str, trade_date: str) -> str:
    """资金情绪 block: fund flow, margin, northbound holdings and 龙虎榜 up to ``trade_date``."""
    code = require_code(ticker)
    return (f"## 资金情绪 (fund sentiment) — {normalize_symbol(ticker)}, as of {trade_date}\n\n"
            + _section("个股资金流 (Eastmoney, main-force / extra-large-order net inflow)", "Eastmoney fund flow",
                       lambda: _fund_flow(code, trade_date))
            + _section("融资融券 (exchange margin detail)", "margin detail", lambda: _margin(code, trade_date))
            + _section("北向资金 (Stock Connect holdings)", "northbound holdings",
                       lambda: _northbound(code, trade_date))
            + _section("龙虎榜 (Eastmoney, seat-level net buying)", "Eastmoney 龙虎榜", lambda: _lhb(code, trade_date)))


# ---------------------------------------------------------------------------
# 市场情绪: 涨停池 / 炸板池 / 跌停池 / 昨日涨停池
# ---------------------------------------------------------------------------
def _pool(kind: str, fn: str, day: pd.Timestamp) -> pd.DataFrame | None:
    """One day's pool, or None when the feed cannot serve that day."""
    key = f"{day:%Y%m%d}"
    try:
        return _dated(kind, key, _closed(day), lambda: getattr(store.ak(), fn)(date=key), f"Eastmoney {kind}")
    except Exception:  # noqa: BLE001 — the pools keep only ~30 trading days
        return None


def _market_day(day: pd.Timestamp) -> dict:
    zt = _pool("zt_pool", "stock_zt_pool_em", day)
    if zt is None or zt.empty:     # a session without a single limit-up does not happen: unobserved
        return {"d": day, "observed": False}
    zb = _pool("zt_pool_zbgc", "stock_zt_pool_zbgc_em", day)
    dt_ = _pool("zt_pool_dtgc", "stock_zt_pool_dtgc_em", day)
    prev = _pool("zt_pool_previous", "stock_zt_pool_previous_em", day)
    boards = pd.to_numeric(zt.get("连板数"), errors="coerce")
    n_zt = len(zt)
    n_zb = None if zb is None else len(zb)
    return {
        "d": day, "observed": True, "final": _closed(day), "zt": zt, "zb": zb, "dt": dt_,
        # On a day whose limit-up pool is served, an empty broken / limit-down pool is a real zero.
        "n_zt": n_zt, "n_zb": n_zb, "n_dt": None if dt_ is None else len(dt_),
        "zb_rate": None if n_zb is None else n_zb / (n_zt + n_zb) * 100,
        "height": int(boards.max()) if boards.notna().any() else None,
        "n_multi": int((boards >= 2).sum()),
        "prev_ret": None if prev is None or prev.empty else _num(pd.to_numeric(prev["涨跌幅"], errors="coerce").mean()),
    }


def get_market_sentiment(trade_date: str, ticker: str | None = None) -> str:
    """市场情绪 block: market-wide limit-up statistics for the last trading days up to ``trade_date``.

    With ``ticker``, also says whether that stock sat in a pool on those days.
    """
    head = f"## 市场情绪 (market sentiment) — whole A-share market, as of {trade_date}\n\n"

    def build() -> str:
        days = [_market_day(d) for d in _trade_days(trade_date, MARKET_DAYS)]
        seen = [x for x in days if x["observed"]]
        missing = [f"{x['d']:%Y-%m-%d}" for x in days if not x["observed"]]
        if not seen:
            return _unavailable("Eastmoney limit-up pools",
                                f"the pools keep only about the last 30 trading days and nothing is cached "
                                f"locally for {', '.join(missing)}, so these days are unobserved")

        def n(v, fmt="{}"):
            return "—" if v is None else fmt.format(v)
        rows = [[f"{x['d']:%Y-%m-%d}" + ("" if x["final"] else " (盘中, not final)"), str(x["n_zt"]),
                 n(x["n_zb"]), n(x["zb_rate"], "{:.1f}%"), n(x["n_dt"]), n(x["height"]), str(x["n_multi"]),
                 "—" if x["prev_ret"] is None else _pct(x["prev_ret"])] for x in seen]
        out = _table(["日期", "涨停家数", "炸板家数", "炸板率", "跌停家数", "最高连板", "连板家数(≥2)",
                      "昨日涨停今日平均涨幅"], rows)
        out += ("\n- 炸板率 = 炸板 / (涨停 + 炸板). 昨日涨停今日平均涨幅 is the limit-up premium (涨停溢价), "
                "the short-term money-making effect.\n")
        if missing:
            out += f"- Unobserved days (beyond the pools' ~30-day history, not cached): {', '.join(missing)}\n"
        last = seen[-1]
        zt = last["zt"]
        boards = pd.to_numeric(zt["连板数"], errors="coerce")
        ladder = []
        for b in sorted(boards.dropna().unique(), reverse=True):
            names = zt.loc[boards == b, "名称"].astype(str).tolist()
            ladder.append(f"{int(b)}板 {len(names)}家" + (f" ({', '.join(names[:5])})" if b >= 3 else ""))
        out += f"- {last['d']:%Y-%m-%d} 连板梯队: " + "; ".join(ladder) + "\n"
        if "所属行业" in zt:
            top = zt["所属行业"].astype(str).value_counts().head(5)
            out += "- 涨停行业分布: " + ", ".join(f"{k} {v}" for k, v in top.items()) + "\n"
        if ticker:
            code = require_code(ticker)
            marks = []
            for x in seen:
                for label, pool in (("涨停", x["zt"]), ("炸板", x["zb"]), ("跌停", x["dt"])):
                    if pool is not None and not pool.empty and "代码" in pool and \
                            (pool["代码"].astype(str).str.zfill(6) == code).any():
                        marks.append(f"{x['d']:%m-%d} {label}")
            out += (f"- {normalize_symbol(ticker)} in the pools: {', '.join(marks)}\n" if marks
                    else f"- {normalize_symbol(ticker)} was in none of the limit-up / broken / limit-down pools on the observed days.\n")
        return out

    return head + _section("涨停 / 炸板 / 跌停 / 连板 (Eastmoney limit-up pools)", "Eastmoney limit-up pools", build)


# ---------------------------------------------------------------------------
# 人气: 东财人气排名 + 千股千评
# ---------------------------------------------------------------------------
def _hot_rank(code: str, end_date: str) -> str:
    symbol = store.to_symbol(code)
    raw = _per_stock("hot_rank", code, lambda: store.ak().stock_hot_rank_detail_em(symbol=symbol),
                     "Eastmoney popularity rank")
    if raw.empty:
        return _unavailable("Eastmoney popularity rank", "the feed returned no rows")
    earliest = pd.to_datetime(raw["时间"], errors="coerce").min()
    df = _upto(raw, "时间", end_date)
    df = df[pd.to_numeric(df["排名"], errors="coerce").notna()]
    if df.empty:
        return _unavailable("Eastmoney popularity rank",
                            f"the feed keeps about a year (from {earliest:%Y-%m-%d}), so {end_date} is unobserved")
    tail = df.tail(POP_DAYS)
    rows = [[f"{r['_d']:%Y-%m-%d}", str(int(_num(r["排名"]))), _pct(_num(r["新晋粉丝"]) * 100, signed=False, digits=1),
             _pct(_num(r["铁杆粉丝"]) * 100, signed=False, digits=1)] for _, r in tail.iterrows()]
    out = _table(["日期", "人气排名", "新晋粉丝", "铁杆粉丝"], rows)
    rank = pd.to_numeric(df["排名"], errors="coerce")
    now, week = int(rank.iloc[-1]), int(rank.iloc[-min(len(rank), POP_DAYS)])
    out += (f"\n- 排名 {now} (rank 1 = most-watched on Eastmoney); {POP_DAYS} rows earlier {week}; "
            f"30-row average {rank.tail(30).mean():.0f}. A falling number is rising attention.\n"
            "- 新晋粉丝 = share of the stock's followers who are new; a jump means fresh, often late, retail attention.\n")
    return out


def _comment(code: str, end_date: str) -> str:
    ak = store.ak
    score = _upto(_per_stock("comment_score", code, lambda: ak().stock_comment_detail_zhpj_lspf_em(symbol=code),
                             "Eastmoney 千股千评 score"), "交易日", end_date)
    focus = _upto(_per_stock("comment_focus", code, lambda: ak().stock_comment_detail_scrd_focus_em(symbol=code),
                             "Eastmoney 千股千评 attention"), "交易日", end_date)
    try:
        desire = _upto(_per_stock("comment_desire", code,
                                  lambda: ak().stock_comment_detail_scrd_desire_em(symbol=code),
                                  "Eastmoney 千股千评 desire"), "交易日期", end_date)
    except Exception:  # noqa: BLE001 — participation desire is a short, optional series
        desire = pd.DataFrame(columns=["_d"])
    days = sorted(set(score["_d"]) | set(focus["_d"]) | set(desire["_d"]))[-POP_DAYS:]
    if not days:
        return _unavailable("Eastmoney 千股千评",
                            f"the feed keeps only about the last 30 trading days, so {end_date} is unobserved")

    def at(df, col, d, fmt):
        hit = df.loc[df["_d"] == d, col] if col in df else []
        return "—" if len(hit) == 0 else fmt(_num(hit.iloc[-1]))
    rows = [[f"{d:%Y-%m-%d}", at(score, "评分", d, lambda v: f"{v:.1f}"),
             at(focus, "用户关注指数", d, lambda v: f"{v:.1f}"),
             at(desire, "参与意愿", d, lambda v: f"{v:.2f}"),
             at(desire, "5日平均参与意愿", d, lambda v: f"{v:.2f}")] for d in days]
    return (_table(["日期", "综合评分", "用户关注指数", "参与意愿", "5日平均参与意愿"], rows)
            + "\n- Eastmoney's own composite indices (0–100); read their direction, not their level alone.\n")


def get_popularity(ticker: str, trade_date: str) -> str:
    """人气 block: Eastmoney popularity rank and 千股千评 up to ``trade_date``."""
    code = require_code(ticker)
    return (f"## 人气 (retail attention) — {normalize_symbol(ticker)}, as of {trade_date}\n\n"
            + _section("东财人气排名 (Eastmoney popularity rank)", "Eastmoney popularity rank",
                       lambda: _hot_rank(code, trade_date))
            + _section("千股千评 (Eastmoney composite score / attention / participation)", "Eastmoney 千股千评",
                       lambda: _comment(code, trade_date)))

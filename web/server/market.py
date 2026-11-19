"""The whole A-share market for the web pages: quotes, industries, main-force flow, search.

  quotes      the daily cross-section the AKShare store keeps under
              ``.akshare_data/snapshots/<YYYYMMDD>/cross_section.parquet`` (every A-share's
              close, change, turnover, amount and volume in lots)
  industries  Shenwan level 1 and 2 from the store's constituent tables
  main flow   Eastmoney's 今日主力净流入 for the latest session (cached for the session);
              when Eastmoney is unreachable, 同花顺's 资金净流入 for that session, which is a
              different measure and is labelled so; for an older date, whichever was cached
  search      a code prefix or a name fragment, against the latest cross-section

Names and industries are today's; they label the table and resolve a name typed
into the analysis box to a code.
"""
from __future__ import annotations

import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.dataflows.symbols import a_share_code, normalize_symbol
from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store
from web.server import limit_detail

XS_FILE = "cross_section.parquet"
_LOCK = threading.Lock()
_TABLES: dict[tuple[str, str], dict] = {}   # (date, flow source) -> table, for the process


def snapshot_root() -> Path:
    return ak_settings.data_dir() / "snapshots"


def available_dates() -> list[str]:
    """Trading days with a whole-market cross-section on disk, newest first (YYYY-MM-DD)."""
    root = snapshot_root()
    if not root.is_dir():
        return []
    days = [d.name for d in root.iterdir() if re.fullmatch(r"\d{8}", d.name) and (d / XS_FILE).is_file()]
    return [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in sorted(days, reverse=True)]


def cross_section(date: str | None = None) -> tuple[str, pd.DataFrame]:
    """(date, the day's cross-section); the latest day when ``date`` is None.

    A day with a daily directory reads it; an earlier trading day is drawn from the
    per-stock history in ``snapshots/base`` (see ``_history_day``).
    """
    dates = available_dates()
    if not dates:
        raise FileNotFoundError("no market snapshot under .akshare_data/snapshots; run `tradingagents-ashare sync`")
    day = date or dates[0]
    if day in dates:
        return day, _read_xs(day.replace("-", ""))
    if day > dates[0]:
        raise NotSynced(day, missing_days())
    xs = _history_day(day)
    if xs.empty:
        raise FileNotFoundError(f"no market data for {day}: not a trading day on record")
    return day, xs


@lru_cache(maxsize=8)
def _read_xs(day: str) -> pd.DataFrame:
    df = pd.read_parquet(snapshot_root() / day / XS_FILE)
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df


def _latest(pattern: str) -> pd.DataFrame | None:
    files = sorted(ak_settings.data_dir().glob(pattern))
    return pd.read_pickle(files[-1]) if files else None


@lru_cache(maxsize=1)
def industries() -> pd.DataFrame:
    """code -> sw1, sw2 (Shenwan names), from the store's latest constituent tables."""
    def level(members: str, names: str, code_col: str, label: str) -> pd.DataFrame:
        cons, table = _latest(members), _latest(names)
        if cons is None or table is None:
            return pd.DataFrame(columns=["code", label])
        lookup = dict(zip(table["行业代码"].astype(str).str.extract(r"(\d{6})")[0], table["行业名称"], strict=False))
        return pd.DataFrame({"code": cons["证券代码"].astype(str).str.zfill(6),
                             label: cons[code_col].astype(str).str.extract(r"(\d{6})")[0].map(lookup)})

    sw1 = level("sw_comp__*.pkl", "sw_first__*.pkl", "行业代码", "sw1").drop_duplicates("code")
    sw2 = level("sw_second_cons__*.pkl", "sw_second__*.pkl", "二级代码", "sw2").drop_duplicates("code")
    return sw1.merge(sw2, on="code", how="outer").set_index("code")


# ---------------------------------------------------------------------------
# Main-force flow
# ---------------------------------------------------------------------------
def _cached_table(kind: str, key: str) -> pd.DataFrame | None:
    path = store.root() / "sentiment" / kind / f"{key}.pkl"
    return pd.read_pickle(path) if path.exists() else None


def _unique(flow: pd.Series) -> pd.Series:
    """One value a code: a ranking fetched page by page while prices move can list a stock on two
    pages (the first, ranked higher when fetched, is kept)."""
    return flow[~flow.index.duplicated(keep="first")]


def main_flow(date: str) -> tuple[pd.Series | None, dict]:
    """(code -> net inflow in yuan, source note) for the session ``date``."""
    from tradingagents.dataflows.vendors.akshare.insiders import cn_number
    from tradingagents.dataflows.vendors.akshare.sentiment import _dated

    key = date.replace("-", "")
    latest = pd.Timestamp(date).date() >= store.last_closed_trade_date()
    final = not store.is_intraday()
    em_error = None
    em = _cached_table("em_fund_flow_today", key)
    if em is None and latest:
        try:
            em = _dated("em_fund_flow_today", key, final,
                        lambda: store.ak().stock_individual_fund_flow_rank(indicator="今日"), "Eastmoney fund flow rank")
        except Exception as e:  # noqa: BLE001 — Eastmoney rate-limits; 同花顺 stands in
            em_error = f"{type(e.__cause__ or e).__name__}"
    if em is not None and len(em) and "今日主力净流入-净额" in em:
        flow = pd.to_numeric(em["今日主力净流入-净额"], errors="coerce")
        flow.index = em["代码"].astype(str).str.zfill(6)
        return _unique(flow), {"source": "eastmoney", "label": "主力净流入", "note": "东方财富 今日主力净流入"}
    ths = _cached_table("ths_fund_flow_now", key)
    if ths is None and latest:
        try:
            ths = _dated("ths_fund_flow_now", key, final,
                         lambda: store.ak().stock_fund_flow_individual(symbol="即时"), "同花顺 fund flow")
        except Exception:  # noqa: BLE001
            ths = None
    if ths is not None and len(ths) and "净额" in ths:
        flow = _unique(pd.Series(ths["净额"].map(cn_number).to_numpy(), index=ths["股票代码"].astype(str).str.zfill(6)))
        why = f"东方财富不可用（{em_error}）" if em_error else "东方财富当日数据未缓存"
        return flow, {"source": "ths", "label": "资金净流入(同花顺)",
                      "note": f"{why}，改用同花顺口径：按主动买卖方向统计全部成交，不分主力，不能与主力净流入比较"}
    reason = "只有最新交易日能取到" if not latest else (f"东方财富 {em_error}，同花顺也不可用" if em_error else "数据源不可用")
    return None, {"source": None, "label": "主力净流入", "note": f"{date} 的资金流不可得：{reason}"}


# ---------------------------------------------------------------------------
# Tables and lookups
# ---------------------------------------------------------------------------
def _num(v):
    return None if pd.isna(v) else float(v)


def _trim(v):
    """A number at the precision shown: whole units for large values, else four decimals."""
    if isinstance(v, float):
        return round(v) if abs(v) >= 1e4 else round(v, 4)
    return v


# ---------------------------------------------------------------------------
# Any trading day: the calendar, history from snapshots/base, and the 5-day change
# ---------------------------------------------------------------------------
def base_through_day() -> str | None:
    from tradingagents.dataflows.vendors.akshare.snapshots import base_through as bt

    d = bt()
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else None


class NotSynced(LookupError):
    """A closed trading day after the newest daily snapshot: it has to be synced first."""

    def __init__(self, day: str, missing: list[str]):
        super().__init__(f"{day} 的行情还没有同步到本地")
        self.day, self.missing = day, missing


def last_closed_day() -> str:
    """The latest trading day that has closed (Beijing time), YYYY-MM-DD."""
    return f"{store.last_closed_trade_date():%Y-%m-%d}"


def trading_days() -> list[str]:
    """Trading days (YYYY-MM-DD) up to the latest closed one, oldest first; days after the
    newest snapshot on disk are listed too (``missing_days``), for they can be synced."""
    dates = available_dates()
    if not dates:
        return []
    cal = [f"{d:%Y-%m-%d}" for d in store.trade_calendar()]
    last = max(dates[0], last_closed_day())
    days = [d for d in cal if d <= last]
    return sorted(set(days) | set(dates))


def missing_days() -> list[str]:
    """Closed trading days after the newest daily snapshot, oldest first."""
    dates = available_dates()
    if not dates:
        return []
    return [d for d in trading_days() if d > dates[0]]


def calendar() -> dict:
    """The date picker's bounds: first and last (closed) trading day, the weekdays in between
    that are not trading days (holidays), so only trading days can be picked, and the days at
    the end not synced yet."""
    days = trading_days()
    if not days:
        return {"min": None, "max": None, "latest": None, "holidays": [], "missing": []}
    trading = set(days)
    weekdays = pd.bdate_range(days[0], days[-1])
    holidays = [f"{d:%Y-%m-%d}" for d in weekdays if f"{d:%Y-%m-%d}" not in trading]
    return {"min": days[0], "max": days[-1], "latest": available_dates()[0], "holidays": holidays,
            "missing": missing_days()}


def invalidate() -> None:
    """Forget everything derived from the snapshots on disk, after a sync added days."""
    with _LOCK:
        _TABLES.clear()
    for f in (_read_xs, pct_5d, _history_day, _daily_stats):
        f.cache_clear()
    from web.server import (  # they import this module: here, not at the top
        breadth,
        breadth_verdict,
        extras,
    )
    breadth.invalidate()
    breadth_verdict.invalidate()
    extras.invalidate()


def _window(day: str, n: int = 5) -> list[str]:
    """The ``n`` trading days ending on ``day``."""
    days = trading_days()
    import bisect

    i = bisect.bisect_right(days, day)
    return days[max(0, i - n):i]


def _scan_base(start: str, end: str) -> pd.DataFrame:
    """Every stock's rows from ``start`` to ``end`` out of ``snapshots/base`` (one file per
    stock, read in parallel): a few seconds for the whole market."""
    from concurrent.futures import ThreadPoolExecutor

    from tradingagents.dataflows.vendors.akshare.snapshots import COLUMNS, _read, master_dir

    lo, hi = pd.Timestamp(start), pd.Timestamp(end)

    def one(p):
        x = _read(p, filters=[("trade_date", ">=", lo), ("trade_date", "<=", hi)])
        return x if len(x) else None
    files = list(master_dir().glob("*.parquet")) if master_dir().is_dir() else []
    with ThreadPoolExecutor(max_workers=8) as ex:
        parts = [x for x in ex.map(one, files) if x is not None]
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
    return out


def _day_cache(day: str) -> Path:
    return store.root() / "web" / "xs" / f"{day.replace('-', '')}.parquet"


@lru_cache(maxsize=32)
def _history_day(day: str) -> pd.DataFrame:
    """A trading day before the daily directories, from ``snapshots/base``, with its 5-day
    change; cached on disk (``.akshare_data/web/xs``), since base no longer changes."""
    path = _day_cache(day)
    if path.exists():
        return pd.read_parquet(path)
    bt = base_through_day()
    if not bt or day > bt:
        return pd.DataFrame()
    window = _window(day)
    rows = _scan_base(window[0], day)
    xs = rows[rows["trade_date"] == day].copy()
    if xs.empty:
        return xs
    xs["pct_5d"] = _compound(window, rows).reindex(xs["code"]).to_numpy() if len(window) == 5 else None
    path.parent.mkdir(parents=True, exist_ok=True)
    xs.reset_index(drop=True).to_parquet(path)
    return xs.reset_index(drop=True)


# ---------------------------------------------------------------------------
# The market's history: rises and falls, limit moves, the median change and turnover
# ---------------------------------------------------------------------------
STATS_RANGES = ("1d", "60d", "6m", "1y")
_STATS_COLS = ["date", "up", "down", "flat", "total", "amount", "median", "limit_up", "limit_down", "broken"]
_EVENT_COLS = ["date", "code", "name", "kind", "pct_chg", "close", "amount", "turnover", "shape"]
STATS_VERSION = 3               # bump when the stats change, so the disk cache is rebuilt
# Price limits by board. Main-board ST stocks moved from 5% to 10% on 2026-07-06 (SSE and
# SZSE trading rules of 2026-04-24); ChiNext went from 10% to 20% on 2020-08-24.
ST_TEN_FROM = "2026-07-06"
CHINEXT_TWENTY_FROM = "2020-08-24"
_EPS = 1e-4


BOARDS = ("主板", "创业板", "科创板", "北交所")


def board_of(code: pd.Series) -> pd.Series:
    """Each code's board: 创业板 (300, 301), 科创板 (688, 689), 北交所 (4xx, 8xx, 920), else 主板."""
    c = code.astype(str).str.zfill(6)
    return pd.Series(np.select(
        [c.str[:3].isin(["300", "301"]), c.str[:3].isin(["688", "689"]), c.str[0].isin(["4", "8"]) | (c.str[:3] == "920")],
        ["创业板", "科创板", "北交所"], "主板"), index=code.index)


def boards(date: str | None = None) -> dict:
    """The day's stocks by board: how many, rose, fell, the median change, amount traded and its
    share, and the limit-ups and limit-downs."""
    day, xs = cross_section(date)
    rows = xs.assign(trade_date=day)
    f = _day_frame(rows)
    f = f.assign(board=board_of(f["code"]).to_numpy())
    total = f["amount"].sum()
    out = []
    for b in BOARDS:
        g = f[f["board"] == b]
        if not len(g):
            continue
        pct = g["pct_chg"]
        out.append({"board": b, "count": int(len(g)), "up": int((pct > 0).sum()), "down": int((pct < 0).sum()),
                    "flat": int((pct == 0).sum()), "median": _trim(_num(pct.median())), "mean": _trim(_num(pct.mean())),
                    "amount": _trim(_num(g["amount"].sum())),
                    "amount_share": _trim(_num(g["amount"].sum() / total * 100)) if total else None,
                    "limit_up": int(g["limit_up"].sum()), "limit_down": int(g["limit_down"].sum())})
    return {"date": day, "boards": out}


def limit_rate(code: pd.Series, name: pd.Series, date: pd.Series) -> pd.Series:
    """Each row's daily price limit (0.05 … 0.30) by board, ST status and date. ST is read off
    the name the row carries; ``snapshots/base`` carries today's name, so a stock that became
    ST lately counts as ST on its earlier days too (it matters only before 2026-07-06)."""
    c = code.astype(str).str.zfill(6)
    d = date.astype(str).str[:10]
    st = name.astype(str).str.upper().str.contains("ST", regex=False)
    rate = pd.Series(0.10, index=c.index)
    rate[st & (d < ST_TEN_FROM)] = 0.05
    rate[c.str[:3].isin(["300", "301"]) & (d >= CHINEXT_TWENTY_FROM)] = 0.20
    rate[c.str[:3].isin(["688", "689"])] = 0.20
    rate[c.str[0].isin(["4", "8"]) | (c.str[:3] == "920")] = 0.30
    return rate


def _limit_price(pre: pd.Series, rate: pd.Series, sign: int, bj: pd.Series) -> pd.Series:
    """The limit price: the previous close moved by the limit, to the fen. Shanghai and
    Shenzhen round half up; the Beijing exchange cuts toward the previous close (9.65 × 1.3 =
    12.545 had an upper limit of 12.54)."""
    raw = pre * (1 + sign * rate) * 100
    rounded = np.floor(raw + 0.5 + 1e-7)
    cut = np.floor(raw + 1e-7) if sign > 0 else np.ceil(raw - 1e-7)
    return pd.Series(np.where(bj, cut, rounded), index=pre.index) / 100


def _day_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """rows with date, pct, amount and the day's limit flags (up, down, broken: touched the
    upper limit but closed below it)."""
    num = lambda c: pd.to_numeric(rows[c], errors="coerce") if c in rows else pd.Series(np.nan, index=rows.index)  # noqa: E731
    pre, close, high, low, open_ = num("pre_close"), num("close"), num("high"), num("low"), num("open")
    date = rows["trade_date"].astype(str).str[:10]
    rate = limit_rate(rows["code"], rows["name"] if "name" in rows else pd.Series("", index=rows.index), date)
    code = rows["code"].astype(str).str.zfill(6)
    bj = code.str[0].isin(["4", "8"]) | (code.str[:3] == "920")
    up_px, down_px = _limit_price(pre, rate, 1, bj), _limit_price(pre, rate, -1, bj)
    # A move past the limit is a day without one (a new listing's first days): no limit move.
    ok = (pre > 0) & (close > 0) & (num("pct_chg").abs() <= rate * 100 + 0.5)
    limit_up = ok & (close >= up_px - _EPS)
    # How a limit-up got there: 一字板 opened at the limit and never left it, T字板 opened at it,
    # traded below and sealed again, 换手板 rose to it during the day.
    at_open, never_left = open_ >= up_px - _EPS, low >= up_px - _EPS
    shape = np.select([limit_up & at_open & never_left, limit_up & at_open, limit_up], ["一字板", "T字板", "换手板"], "")
    return pd.DataFrame({
        "date": date, "code": code,
        "name": rows["name"].astype(str) if "name" in rows else "", "pct_chg": num("pct_chg"),
        "close": close, "amount": num("amount"), "turnover": num("turnover"), "shape": shape,
        "limit_up": limit_up,
        "limit_down": ok & (close <= down_px + _EPS),
        "broken": ok & (high >= up_px - _EPS) & (close < up_px - _EPS),
    })


def _stats_of(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(one row per day: counts, the amount traded in yuan, the median change and limit
    moves; one row per limit move: up, down or broken)."""
    if not len(rows):
        return pd.DataFrame(columns=_STATS_COLS), pd.DataFrame(columns=_EVENT_COLS)
    x = _day_frame(rows)
    pct = x["pct_chg"]
    x = x.assign(up=pct > 0, down=pct < 0, flat=pct == 0)
    g = x.groupby("date").agg(up=("up", "sum"), down=("down", "sum"), flat=("flat", "sum"), total=("up", "size"),
                              amount=("amount", "sum"), median=("pct_chg", "median"), limit_up=("limit_up", "sum"),
                              limit_down=("limit_down", "sum"), broken=("broken", "sum")).reset_index()
    kind = np.select([x["limit_up"], x["limit_down"], x["broken"]], ["up", "down", "broken"], "")
    ev = x.assign(kind=kind)
    ev = ev[ev["kind"] != ""][_EVENT_COLS].reset_index(drop=True)
    return g[_STATS_COLS], ev


def _stats_cache() -> Path:
    return store.root() / "web" / f"market_stats_v{STATS_VERSION}.parquet"


def _events_cache() -> Path:
    return store.root() / "web" / f"limit_events_v{STATS_VERSION}.parquet"


def _base_stats(days: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The stats and limit moves of days in ``snapshots/base``: worked out once (a scan of
    every stock's file), then kept on disk, since base no longer changes."""
    if not days:
        return pd.DataFrame(columns=_STATS_COLS), pd.DataFrame(columns=_EVENT_COLS)
    path, epath = _stats_cache(), _events_cache()
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=_STATS_COLS)
    events = pd.read_parquet(epath) if epath.exists() else pd.DataFrame(columns=_EVENT_COLS)
    todo = sorted(set(days) - set(have["date"]))
    if todo:
        # Opening every stock's file is most of the cost, whatever the span: take a year
        # at a time, so switching between 60 days, six months and a year scans once.
        lo = min(todo[0], _range_start(todo[-1], "1y", todo))
        fresh, fresh_ev = _stats_of(_scan_base(lo, todo[-1]))
        none = [d for d in todo if d not in set(fresh["date"])]
        fresh = fresh[~fresh["date"].isin(have["date"])]
        fresh_ev = fresh_ev[fresh_ev["date"].isin(set(fresh["date"]))]
        if none:          # a trading day no stock traded on (none such, but be safe): zeros
            fresh = pd.concat([fresh, pd.DataFrame({c: [0] * len(none) for c in _STATS_COLS[1:]} | {"date": none})])
        have = pd.concat([have, fresh], ignore_index=True).sort_values("date").reset_index(drop=True)
        events = pd.concat([events, fresh_ev], ignore_index=True).sort_values(["date", "code"]).reset_index(drop=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        events.to_parquet(epath)          # events first: stats on disk mean their events are too
        have.to_parquet(path)
    return have[have["date"].isin(days)], events[events["date"].isin(days)]


@lru_cache(maxsize=64)
def _daily_stats(day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _stats_of(_read_xs(day.replace("-", "")).assign(trade_date=day))


def _range_start(end: str, rng: str, days: list[str]) -> str:
    """The first day of ``rng`` ending on ``end``: 1d the day, 60d sixty trading days, 6m and 1y
    the same date six or twelve months back (a 31st that month lacks lands on its last day)."""
    if rng == "1d":
        return end
    if rng == "60d":
        return days[-60] if len(days) >= 60 else days[0]
    y, m, d = (int(v) for v in end.split("-"))
    m -= 6 if rng == "6m" else 12
    while m <= 0:
        y, m = y - 1, m + 12
    last = pd.Timestamp(year=y, month=m, day=1).days_in_month
    return f"{y:04d}-{m:02d}-{min(d, last):02d}"


def _days_on_record(end: str | None) -> list[str]:
    """Trading days with data (a daily snapshot or base) up to ``end``."""
    daily, bt = set(available_dates()), base_through_day()
    days = [d for d in trading_days() if d in daily or (bt and d <= bt)]
    if end:
        days = [d for d in days if d <= end]
    if not days:
        raise FileNotFoundError(f"no market data on or before {end}")
    return days


def _span_stats(span: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = set(available_dates())
    base_s, base_e = _base_stats([d for d in span if d not in daily])
    parts = [_daily_stats(d) for d in span if d in daily]
    stats = [base_s, *[p[0] for p in parts]]
    events = [base_e, *[p[1] for p in parts]]
    cat = lambda xs, cols: pd.concat([x for x in xs if len(x)], ignore_index=True) if any(len(x) for x in xs) \
        else pd.DataFrame(columns=cols)  # noqa: E731
    return cat(stats, _STATS_COLS).sort_values("date"), cat(events, _EVENT_COLS)


# Indexes to set against the stocks: the local series name and the index code.
BENCHMARKS = {"上证指数": ("sh_comp", "sh000001"), "沪深300": ("idx_hs300", "sh000300"),
              "中证500": ("idx_zz500", "sh000905"), "中证1000": ("idx_zz1000", "sh000852"),
              "创业板指": ("idx_cyb", "sz399006"), "创业板综": ("idx_cybz", "sz399102"),
              "科创综指": ("idx_kcz", "sh000680"), "科创50": ("idx_kc50", "sh000688")}
_INDEX_MEMO: dict[tuple[str, str], pd.DataFrame] = {}


def _index_daily(symbol: str, start: str) -> pd.DataFrame:
    """An index's daily bars from ``start`` (YYYYMMDD): Eastmoney, or Sina when Eastmoney fails
    (it rate-limits an IP that asks too often; Sina sends the whole history, cut here)."""
    try:
        return store.ak().stock_zh_index_daily_em(symbol=symbol, start_date=start)
    except Exception as e:  # noqa: BLE001
        df = store.ak().stock_zh_index_daily(symbol=symbol)
        if df is None or not len(df):
            raise LookupError(f"{symbol}: Eastmoney {type(e).__name__}, Sina empty") from e
        return df[pd.to_datetime(df["date"]) >= pd.Timestamp(start)].reset_index(drop=True)


def index_closes(name: str) -> pd.DataFrame:
    """An index's daily closes (date, close), kept up to date in ``ts/`` (Eastmoney, or Sina when
    Eastmoney fails), at most one download per index per closed trading day."""
    series, symbol = BENCHMARKS[name]
    key = (series, last_closed_day())
    if key not in _INDEX_MEMO:
        df = store.incremental(series, lambda s: _index_daily(symbol, s), "date", "20240101")
        _INDEX_MEMO[key] = pd.DataFrame({"date": store.to_local_dates(df["date"]).dt.strftime("%Y-%m-%d"),
                                         "close": pd.to_numeric(df["close"], errors="coerce")}).dropna()
    return _INDEX_MEMO[key]


def market_stats(end: str | None = None, rng: str = "60d") -> dict:
    """The market day by day over ``rng`` (1d, 60d, 6m, 1y) to ``end`` (the latest day on disk
    by default): rises, falls, unchanged, the median change, limit moves and the amount
    traded, every A-share on record; and the main indexes' closes over the same days."""
    if rng not in STATS_RANGES:
        raise ValueError(f"range 只能是 {', '.join(STATS_RANGES)}")
    days = _days_on_record(end)
    end = days[-1]
    start = _range_start(end, rng, days)
    span = [d for d in days if d >= start]
    stats, _ = _span_stats(span)
    rows = [{"date": r.date, "up": int(r.up), "down": int(r.down), "flat": int(r.flat), "total": int(r.total),
             "amount": float(r.amount), "median": _trim(_num(r.median)), "limit_up": int(r.limit_up),
             "limit_down": int(r.limit_down), "broken": int(r.broken)}
            for r in stats.itertuples(index=False) if r.total]
    # The index closes from the trading day before the span, so each line starts at 0%.
    prev = days[days.index(span[0]) - 1] if days.index(span[0]) else span[0]
    indexes, index_error = {}, None
    for name in BENCHMARKS:
        try:
            x = index_closes(name)
            x = x[(x["date"] >= prev) & (x["date"] <= end)]
            indexes[name] = [{"date": d, "close": float(c)} for d, c in zip(x["date"], x["close"], strict=False)]
        except Exception as e:  # noqa: BLE001 - the stocks' stats stand without the indexes
            index_error = f"指数行情获取失败：{type(e).__name__}"
    return {"range": rng, "start": start, "end": end, "days": rows, "indexes": indexes, "index_base": prev,
            "index_error": index_error,
            "note": ("按本地个股日线统计（全部A股，含北交所），成交额为各股成交额之和；涨跌停按板块涨跌幅计算"
                     "（主板 10%、ST 5%（2026-07-06 起 10%）、创业板/科创板 20%、北交所 30%）")}


def limit_board(date: str | None = None) -> dict:
    """The day's limit moves: limit-up stocks by how many days in a row they have closed at
    the limit (连板), the ones that touched it but closed below (炸板), and limit-down ones."""
    days = _days_on_record(date)
    day = days[-1]
    span = days[-40:]                      # enough to count back any run of limit-ups
    _, events = _span_stats(span)
    ups = {d: set(g["code"]) for d, g in events[events["kind"] == "up"].groupby("date")}
    today = events[events["date"] == day]
    sectors = industries()

    def streak(code: str) -> int:
        n = 0
        for d in reversed(span):
            if code not in ups.get(d, ()):
                break
            n += 1
        return n

    def item(r) -> dict:
        # The Shenwan level-2 industry (level 1 when a stock has no level-2 one).
        ind = l1 = None
        if r.code in sectors.index:
            l1 = sectors["sw1"].get(r.code)
            ind = sectors["sw2"].get(r.code)
            if not isinstance(ind, str):
                ind = l1
        return {"code": r.code, "name": re.sub(r"\s+", "", str(r.name)), "pct_chg": _trim(_num(r.pct_chg)),
                "close": _trim(_num(r.close)), "amount": _trim(_num(r.amount)),
                "turnover": _trim(_num(getattr(r, "turnover", None))),
                "industry": ind if isinstance(ind, str) else None,
                "industry_l1": l1 if isinstance(l1, str) else None}

    # The reason, sealing times and orders at the limit come from the limit-up pools.
    detail = limit_detail.details(day).set_index("code") if (today["kind"] == "up").any() else pd.DataFrame()

    def extra(r) -> dict:
        d = detail.loc[r.code] if r.code in detail.index else None
        get = lambda k: None if d is None or pd.isna(d[k]) else d[k]  # noqa: E731
        return {"shape": getattr(r, "shape", None) or None, "reason": get("reason"),
                "first_time": get("first_time"), "last_time": get("last_time"),
                "order_volume": _trim(_num(get("order_volume"))), "order_amount": _trim(_num(get("order_amount")))}

    up = [{**item(r), **extra(r), "streak": streak(r.code)} for r in today[today["kind"] == "up"].itertuples(index=False)]
    ladder: dict[int, list] = {}
    for x in sorted(up, key=lambda x: -(x["amount"] or 0)):
        ladder.setdefault(x["streak"], []).append(x)
    broken = sorted((item(r) for r in today[today["kind"] == "broken"].itertuples(index=False)),
                    key=lambda x: -(x["pct_chg"] or 0))
    # When the limit-downs first and last sealed the lower limit, from the limit-down pools.
    downs = today[today["kind"] == "down"]
    ddetail = limit_detail.details(day, side="down").set_index("code") if len(downs) else pd.DataFrame()

    def times(r) -> dict:
        d = ddetail.loc[r.code] if r.code in ddetail.index else None
        get = lambda k: None if d is None or pd.isna(d[k]) else d[k]  # noqa: E731
        return {"first_time": get("first_time"), "last_time": get("last_time")}

    down = sorted(({**item(r), **times(r)} for r in downs.itertuples(index=False)),
                  key=lambda x: x["pct_chg"] or 0)
    touched = len(up) + len(broken)
    return {"date": day, "limit_up": len(up), "limit_down": len(down), "broken": len(broken),
            "broken_rate": _trim(len(broken) / touched * 100) if touched else None,
            "max_streak": max((x["streak"] for x in up), default=0),
            "ladder": [{"streak": k, "stocks": v} for k, v in sorted(ladder.items(), reverse=True)],
            "broken_list": broken, "down_list": down,
            "detail_source": sorted(set(detail["source"])) if len(detail) else []}


def _compound(window: list[str], base_rows: pd.DataFrame | None = None) -> pd.Series:
    """code -> change over ``window`` (%), compounding each session's change. Each session's
    change is against its adjusted previous close, so an ex-dividend day does not distort it;
    a stock with no row on a session (suspended) counts as unchanged that day."""
    daily = set(available_dates())
    factor = None
    for d in window:
        if d in daily:
            x = _read_xs(d.replace("-", "")).set_index("code")["pct_chg"]
        else:
            part = base_rows[base_rows["trade_date"] == d] if base_rows is not None else pd.DataFrame()
            x = part.set_index("code")["pct_chg"] if len(part) else pd.Series(dtype=float)
        f = 1 + pd.to_numeric(x, errors="coerce").fillna(0) / 100
        factor = f if factor is None else factor.mul(f, fill_value=1)
    return (factor - 1) * 100


@lru_cache(maxsize=8)
def pct_5d(day: str) -> pd.Series | None:
    """code -> change over the five trading days to ``day`` (%); None when a day of the
    five has no data on disk (neither a daily directory nor base)."""
    window = _window(day)
    if len(window) < 5:
        return None
    daily, bt = set(available_dates()), base_through_day()
    if any(d not in daily and not (bt and d <= bt) for d in window):
        return None
    in_base = [d for d in window if d not in daily]
    rows = _scan_base(in_base[0], in_base[-1]) if in_base else None
    return _compound(window, rows)


def market_table(date: str | None = None) -> dict:
    """Every A-share on ``date`` (latest by default): quote, the day's range, 5-day change,
    industry, main-force flow, TTM earnings, market value and shares."""
    day, xs = cross_section(date)
    flow, flow_meta = main_flow(day)
    ttm, ttm_label = ttm_profit(day)
    cache_key = (day, str(flow_meta.get("source")), ttm_label)
    with _LOCK:
        if cache_key in _TABLES:
            return _TABLES[cache_key]
    df = xs.copy().join(industries(), on="code")
    df["main_flow"] = df["code"].map(flow) if flow is not None else None
    if "pct_5d" not in df:                       # a historical day carries it already
        five = pct_5d(day)
        df["pct_5d"] = df["code"].map(five) if five is not None else None
    df["ttm"] = df["code"].map(ttm) if ttm is not None else None
    rows = []
    for r in df.itertuples(index=False):
        close, pre = _num(r.close), _num(getattr(r, "pre_close", None))
        open_ = _num(getattr(r, "open", None))
        total_mv, float_mv = _num(r.total_mv), _num(getattr(r, "float_mv", None))
        if float_mv is None and close:
            # base history has no market values; turnover = volume / floating shares gives
            # the day's floating shares exactly (volume in lots, turnover in %).
            vol, turn = _num(r.volume), _num(r.turnover)
            float_mv = vol * 1e4 / turn * close if vol and turn else None
        shares = total_mv / close if total_mv and close else None
        profit = _num(r.ttm)
        eps = profit / shares if profit is not None and shares else None
        rows.append({
            "code": r.code, "name": re.sub(r"\s+", "", str(r.name)), "pct_chg": _num(r.pct_chg), "price": close,
            "exchange": _exchange(r.code),
            "main_flow": _num(r.main_flow), "open_pct": (open_ / pre - 1) * 100 if open_ and pre else None,
            "high": _num(getattr(r, "high", None)), "low": _num(getattr(r, "low", None)),
            "amount": _num(r.amount), "volume": _num(r.volume), "pct_5d": _num(r.pct_5d),
            "amplitude": _num(getattr(r, "amplitude", None)),
            "industry": r.sw1 if isinstance(r.sw1, str) else None,
            "sub_industry": r.sw2 if isinstance(r.sw2, str) else None, "turnover": _num(r.turnover),
            "pe_ttm": close / eps if eps and close else None, "eps_ttm": eps,
            "total_mv": total_mv, "total_shares": shares,
            "float_mv": float_mv, "float_shares": float_mv / close if float_mv and close else None,
        })
    rows = [{k: _trim(v) for k, v in row.items()} for row in rows]
    no_total = not any(r["total_mv"] for r in rows)
    up = sum(1 for r in rows if (r["pct_chg"] or 0) > 0)
    down = sum(1 for r in rows if (r["pct_chg"] or 0) < 0)
    table = {"date": day, "dates": available_dates(), "flow": flow_meta, "ttm": ttm_label,
             "breadth": {"total": len(rows), "up": up, "down": down, "flat": len(rows) - up - down},
             "note": ("历史行情不含总股本：总市值、总股本、市盈TTM、每股收益TTM 只在每日快照的日期有；"
                      "流通股与流通值由当日换手率推算") if no_total else None,
             "count": len(rows), "rows": rows}
    with _LOCK:
        _TABLES[cache_key] = table
    return table


def _names() -> pd.DataFrame:
    _, xs = cross_section()
    out = xs[["code", "name"]].copy()
    out["name"] = out["name"].astype(str).str.replace(r"\s+", "", regex=True)
    out["plain"] = out["name"].str.replace(r"^\*?S?\*?ST", "", regex=True).str.upper()
    return out


def search(q: str, limit: int = 10) -> list[dict]:
    """Stocks whose code starts with ``q`` or whose name contains it; exact matches first."""
    q = re.sub(r"\s+", "", q or "").upper()
    if not q:
        return []
    df = _names()
    code_q = re.sub(r"^(SH|SZ|BJ)|\.(SS|SH|SZ|BJ)$", "", q)
    hit = df[df["code"].str.startswith(code_q) | df["name"].str.upper().str.contains(q, regex=False)
             | df["plain"].str.contains(q, regex=False)]
    hit = hit.assign(rank=(hit["code"] != code_q) & (hit["name"].str.upper() != q) & (hit["plain"] != q))
    hit = hit.sort_values(["rank", "code"]).head(limit)
    return [{"code": r.code, "name": r.name, "symbol": normalize_symbol(r.code)} for r in hit.itertuples()]


def resolve_ticker(q: str) -> str:
    """A stock code from a code or a name; raises ValueError naming the candidates when unsure.

    A-share codes and foreign tickers (AAPL, 0700.HK) pass through; a Chinese name
    must match exactly one stock, or be the only one containing it.
    """
    raw = (q or "").strip()
    if not raw:
        raise ValueError("请输入股票代码或名称")
    if a_share_code(raw) or re.fullmatch(r"[A-Za-z0-9.\-^=]{1,20}", raw):
        return raw
    try:
        found = search(raw, limit=20)
    except FileNotFoundError as e:
        raise ValueError(f"无法按名称查找股票：{e}") from e
    key = re.sub(r"\s+", "", raw).upper()
    exact = [f for f in found if f["name"].upper() == key or re.sub(r"^\*?S?\*?ST", "", f["name"]).upper() == key]
    if len(exact) == 1:
        return exact[0]["code"]
    if len(found) == 1:
        return found[0]["code"]
    if not found:
        raise ValueError(f"找不到名称包含「{raw}」的股票")
    names = "、".join(f"{f['name']}({f['code']})" for f in found[:8])
    raise ValueError(f"「{raw}」对应多只股票：{names}，请输入代码或完整名称")


def quote(code: str) -> dict | None:
    """One stock's row of the latest market table."""
    code = a_share_code(code) or code
    table = market_table()
    for row in table["rows"]:
        if row["code"] == code:
            return {**row, "date": table["date"], "flow": table["flow"], "symbol": normalize_symbol(code)}
    return None


# ---------------------------------------------------------------------------
# A stock's whole daily history from the local store
# ---------------------------------------------------------------------------
def base_through() -> str | None:
    """The last day ``snapshots/base`` covers (YYYY-MM-DD), from the store's _meta.json."""
    import json

    try:
        day = json.loads((snapshot_root() / "_meta.json").read_text()).get("base_through")
    except (OSError, ValueError):
        return None
    return f"{day[:4]}-{day[4:6]}-{day[6:]}" if day and len(day) == 8 else None


def history(code: str, end: str | None = None) -> dict:
    """Every daily bar of an A-share since listing: ``snapshots/base`` (to base_through)
    then the daily cross-sections after it. Prices are unadjusted; volume is in lots (手).

    Raises FileNotFoundError when the store has no data for the stock.
    """
    from tradingagents.dataflows.symbols import exchange_prefix
    from tradingagents.dataflows.vendors.akshare.snapshots import load_stock

    c = a_share_code(code)
    ex = exchange_prefix(c) if c else None
    if not ex:
        raise FileNotFoundError(f"{code} is not an A-share stock")
    df = load_stock(f"{ex}{c}", end)
    df = df.dropna(subset=["open", "high", "low", "close"])
    through = base_through()
    bars = [{"time": f"{r.trade_date:%Y-%m-%d}", "open": float(r.open), "high": float(r.high), "low": float(r.low),
             "close": float(r.close), "volume": _num(r.volume), "amount": _num(r.amount), "pct_chg": _num(r.pct_chg),
             "turnover": _num(r.turnover)} for r in df.itertuples(index=False)]
    after = sum(1 for b in bars if through and b["time"] > through)
    return {
        "symbol": normalize_symbol(c), "name": re.sub(r"\s+", "", str(df["name"].iloc[-1])) if len(df) else None,
        "source": "snapshot", "adjust": "不复权", "volume_unit": "手",
        "base_through": through, "after_base": after, "bars": bars,
    }


# ---------------------------------------------------------------------------
# Watchlist rows: the market row plus the day's range, 5-day change and TTM earnings
# ---------------------------------------------------------------------------
def _earnings(period: str) -> pd.Series | None:
    """code -> year-to-date net profit for a report period (YYYYMMDD), from the store's
    yjbb tables, fetching (and caching under the store's own name) a period it lacks."""
    from tradingagents.dataflows.vendors.akshare.financials import YJBB_HIST_COLS

    root = ak_settings.data_dir()
    files = sorted(root.glob(f"yjbb__P{period}.pkl")) + sorted(root.glob(f"yjbb_hist_{period}__P{period}.pkl"))
    if files:
        df = pd.read_pickle(files[0])
    else:
        try:
            df = store.cached(f"yjbb_hist_{period}",
                              lambda: store.ak().stock_yjbb_em(date=period)[YJBB_HIST_COLS], ("period", period, False))
        except Exception:  # noqa: BLE001 — TTM is then shown as unavailable
            return None
    out = pd.to_numeric(df["净利润-净利润"], errors="coerce")
    out.index = df["股票代码"].astype(str).str.zfill(6)
    return out[~out.index.duplicated()]


# Statutory deadlines for each report period: (period end MMDD, deadline, the deadline's year offset).
_DEADLINES = (("0331", "0430", 0), ("0630", "0831", 0), ("0930", "1031", 0), ("1231", "0430", 1))


def period_for(day: str) -> str:
    """The latest report period (YYYYMMDD) every company had to have published by ``day``."""
    d = pd.Timestamp(day)
    best = None
    for year in (d.year - 2, d.year - 1, d.year):
        for end, deadline, offset in _DEADLINES:
            due = pd.Timestamp(f"{year + offset}{deadline}")
            if due <= d and (best is None or f"{year}{end}" > best):
                best = f"{year}{end}"
    return best


def ttm_profit(day: str | None = None) -> tuple[pd.Series | None, str]:
    """(code -> trailing-twelve-month net profit, what it covers): the period's year to date,
    plus the last annual report, less the same period a year before. The period is the latest
    published by ``day`` (by the statutory deadlines), or the store's latest without one."""
    if day is None or day >= available_dates()[0]:
        latest = sorted(ak_settings.data_dir().glob("yjbb__P*.pkl"))
        if latest:
            return _ttm(latest[-1].stem.split("__P")[-1])
        if day is None:
            return None, "无业绩数据"
    return _ttm(period_for(day))


@lru_cache(maxsize=4)
def _ttm(period: str) -> tuple[pd.Series | None, str]:
    """TTM net profit as of a report period; recomputed when the store syncs a newer period."""
    year, mmdd = int(period[:4]), period[4:]
    now = _earnings(period)
    if now is None:
        return None, "无业绩数据"
    if mmdd == "1231":
        return now, f"{year} 年报"
    annual, same = _earnings(f"{year - 1}1231"), _earnings(f"{year - 1}{mmdd}")
    if annual is None or same is None:
        return None, f"缺少 {year - 1} 年报或同期数据"
    label = {"0331": "一季报", "0630": "半年报", "0930": "三季报"}.get(mmdd, mmdd)
    return now + annual - same, f"截至 {year} {label}的近四个季度"


def watch_rows(codes: list[str]) -> dict:
    """The watchlist's rows of the latest market table, in the order given."""
    table = market_table()
    by_code = {r["code"]: r for r in table["rows"]}
    rows = [{**by_code[c], "missing": False} if c in by_code else {"code": c, "name": None, "missing": True}
            for c in codes]
    return {"date": table["date"], "flow": table["flow"], "ttm": table["ttm"], "rows": rows}


def _exchange(code: str) -> str | None:
    """SH, SZ or BJ for an A-share code."""
    from tradingagents.dataflows.symbols import exchange_prefix

    return exchange_prefix(code)


# ---------------------------------------------------------------------------
# Index constituents (沪深300 ...), for the market page's universe filter
# ---------------------------------------------------------------------------
INDEXES = {"000300": "沪深300"}


def index_members(index: str) -> dict:
    """An index's constituent codes today: China Securities Index's own list, else Sina's;
    cached for the week. ValueError for an index not offered."""
    if index not in INDEXES:
        raise ValueError(f"不支持的指数：{index}")

    def fetch() -> pd.DataFrame:
        try:
            df = store.ak().index_stock_cons_csindex(symbol=index)
            return pd.DataFrame({"code": df["成分券代码"].astype(str).str.zfill(6), "date": df["日期"].astype(str)})
        except Exception:  # noqa: BLE001 — Sina lists the same constituents
            df = store.ak().index_stock_cons(symbol=index)
            return pd.DataFrame({"code": df["品种代码"].astype(str).str.zfill(6), "date": ""})

    try:
        df = store.cached(f"index_cons_{index}", lambda: store.call(fetch, f"{INDEXES[index]} constituents"), "weekly")
    except Exception as e:  # noqa: BLE001
        raise FileNotFoundError(f"{INDEXES[index]}成分股取不到：{str(e)[:120]}") from e
    as_of = str(df["date"].iloc[0]) if len(df) and str(df["date"].iloc[0]) else None
    return {"index": index, "name": INDEXES[index], "as_of": as_of, "codes": df["code"].tolist()}

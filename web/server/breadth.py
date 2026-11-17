"""The market's breadth and short-term mood, day by day, from every stock's daily history:

  涨停溢价    how yesterday's limit-up stocks did today: their average change and the share
              that rose; 晋级率, the share that closed at the limit again (首板 -> 2 板,
              2 板 -> 3 板, 3 板及以上 -> 更高, and every 连板 stock together).
  大小盘风格  the median change of the largest 300 stocks by float market value (≈ 沪深300),
              the next 500 (≈ 中证500), the next 1000 (≈ 中证1000) and the smallest 400
              (微盘); ST stocks are left out.
  新高新低    stocks closing above (below) every close of the past 59 (249) trading days: 60-day
              and 250-day (52-week) highs and lows, on prices adjusted for dividends and splits.
  均线上方占比 the share of stocks closing above their 20-day and 60-day moving average.
  空间板      the day's highest run of limit-ups (最高连板) and how many stocks are on a run of
              two or more (连板家数).
  情绪综合分  six readings of the day's short-term mood, each put on 0–100, and their average:
              涨跌比 (rises among rises and falls), 涨停跌停比, 封板率 (limit-ups among those
              that touched the limit), 涨停溢价 (−5% … +5%), 晋级率 (0 … 40%) and 空间板
              (1 … 8 boards).

Prices are adjusted by compounding each day's change (which is against the adjusted
previous close), so an ex-dividend day is no fall. A suspended day counts as unchanged.
Before the daily snapshots, the float market value of a day is estimated as that day's close
times the latest float shares (base keeps no market value), which is near enough to rank by.

Two years of ``snapshots/base`` (one scan, a few seconds) are kept in
``.akshare_data/web/panel_v1_<base through>.parquet``; the daily snapshots are read as they
are. The day-by-day results are worked out for every day at once and kept for the process.
"""
from __future__ import annotations

import threading
from functools import lru_cache

import numpy as np
import pandas as pd

from tradingagents.dataflows.vendors.akshare import store
from web.server import market

PANEL_VERSION = 1
LOOKBACK = 520                 # trading days of base kept: 250-day highs over a year's range
SIZE_BANDS = (("大盘", 0, 300), ("中盘", 300, 800), ("小盘", 800, 1800), ("微盘", -400, None))
BAND_RULES = {"大盘": "流通市值前 300（≈沪深300）", "中盘": "第 301–800（≈中证500）",
              "小盘": "第 801–1800（≈中证1000）", "微盘": "最小的 400 只"}
MIN_STOCKS = 100              # fewer stocks with enough history on a day: no breadth figure
MIN_BAND = 50                 # fewer stocks in a size band on a day: no median
_FIXED = ["prem_n", "prem_avg", "prem_up", "promo_1", "promo_2", "promo_3", "promo_multi", "promo_all",
          "nh60", "nl60", "nh250", "nl250", "ma20", "ma60", "height", "multi_n",
          "mood", *[f"m_{k}" for k in ("updown", "limit", "seal", "prem", "promo", "height")]]
MOOD_PARTS = {"updown": "涨跌比", "limit": "涨停跌停比", "seal": "封板率", "prem": "涨停溢价", "promo": "晋级率", "height": "空间板"}


def columns() -> list[str]:
    return [*_FIXED, *[f"size_{b[0]}" for b in SIZE_BANDS]]
_lock = threading.Lock()


def _panel_path(through: str):
    return store.root() / "web" / f"panel_v{PANEL_VERSION}_{through.replace('-', '')}.parquet"


def _base_panel() -> pd.DataFrame:
    """date, code, name, pct_chg, close for the last LOOKBACK trading days of base."""
    bt = market.base_through_day()
    if not bt:
        return pd.DataFrame(columns=["date", "code", "name", "pct_chg", "close"])
    path = _panel_path(bt)
    if path.exists():
        return pd.read_parquet(path)
    days = [d for d in market.trading_days() if d <= bt]
    rows = market._scan_base(days[-LOOKBACK] if len(days) >= LOOKBACK else days[0], bt)
    out = pd.DataFrame({
        "date": rows["trade_date"].astype(str).str[:10], "code": rows["code"].astype(str).str.zfill(6),
        "name": rows["name"].astype(str),
        "pct_chg": pd.to_numeric(rows["pct_chg"], errors="coerce").astype("float32"),
        "close": pd.to_numeric(rows["close"], errors="coerce").astype("float32"),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob(f"panel_v{PANEL_VERSION}_*.parquet"):   # base moved on: one panel kept
        old.unlink(missing_ok=True)
    out.to_parquet(path)
    return out


def _wide(panel: pd.DataFrame, col: str) -> pd.DataFrame:
    return panel.pivot_table(index="date", columns="code", values=col, aggfunc="last").sort_index()


@lru_cache(maxsize=1)
def _table(key: tuple) -> pd.DataFrame:
    """Every day's figures (index: date, columns: ``columns()``); ``key`` names the data it reads."""
    daily = [d for d in market.available_dates() if d > (market.base_through_day() or "")]
    parts, mv_parts = [_base_panel()], []
    for d in daily:
        xs = market._read_xs(d.replace("-", ""))
        code = xs["code"].astype(str).str.zfill(6)
        parts.append(pd.DataFrame({"date": d, "code": code, "name": xs["name"].astype(str),
                                   "pct_chg": pd.to_numeric(xs["pct_chg"], errors="coerce"),
                                   "close": pd.to_numeric(xs["close"], errors="coerce")}))
        if "float_mv" in xs:
            mv_parts.append(pd.DataFrame({"date": d, "code": code, "mv": pd.to_numeric(xs["float_mv"], errors="coerce")}))
    panel = pd.concat([p for p in parts if len(p)], ignore_index=True)
    panel = panel[panel["close"] > 0]
    if panel.empty:
        return pd.DataFrame(columns=columns())
    pct, close = _wide(panel, "pct_chg"), _wide(panel, "close")
    dates = list(pct.index)
    traded = pct.notna()

    # Adjusted closes: each day's change compounded; a suspended day unchanged; nothing before listing.
    listed = traded.cummax()
    adj = (1 + pct.fillna(0) / 100).cumprod().where(listed)
    out = pd.DataFrame(index=pct.index)

    for n in (60, 250):
        prev_hi = adj.shift(1).rolling(n - 1, min_periods=n - 1).max()
        prev_lo = adj.shift(1).rolling(n - 1, min_periods=n - 1).min()
        enough = prev_hi.notna() & traded
        out[f"nh{n}"] = ((adj > prev_hi * (1 + 1e-9)) & enough).sum(axis=1)
        out[f"nl{n}"] = ((adj < prev_lo * (1 - 1e-9)) & enough).sum(axis=1)
        # Not enough history on a day for any stock: no figure.
        out.loc[enough.sum(axis=1) < MIN_STOCKS, [f"nh{n}", f"nl{n}"]] = np.nan
    for n in (20, 60):
        ma = adj.rolling(n, min_periods=n).mean()
        base = traded & ma.notna()
        share = ((adj > ma) & base).sum(axis=1) / base.sum(axis=1).replace(0, np.nan) * 100
        out[f"ma{n}"] = share.where(base.sum(axis=1) >= MIN_STOCKS)

    # Size bands by float market value: the day's own where a snapshot has it, else the day's
    # close times the latest float shares.
    names = panel.drop_duplicates("code", keep="last").set_index("code")["name"]
    st = names.reindex(pct.columns).fillna("").str.upper().str.contains("ST").to_numpy()
    mv = pd.DataFrame(np.nan, index=pct.index, columns=pct.columns)
    if mv_parts:
        mvp = pd.concat(mv_parts, ignore_index=True)
        mvw = mvp.pivot_table(index="date", columns="code", values="mv", aggfunc="last").reindex(columns=pct.columns)
        last = mvw.ffill().iloc[-1]
        shares = last / close.loc[mvw.index[-1]].reindex(pct.columns)
        mv = close * shares
        mv.loc[mvw.index] = mvw.reindex(index=mvw.index).combine_first(mv.loc[mvw.index])
    rank_mv = mv.where(traded).where(~pd.Series(st, index=pct.columns), axis=1)
    rank = rank_mv.rank(axis=1, ascending=False, method="first")
    count = rank_mv.notna().sum(axis=1)
    for name, lo, hi in SIZE_BANDS:
        # A negative start: the smallest |lo|.
        mask = rank.gt(count + lo, axis=0) if lo < 0 else (rank > lo) & (rank <= hi)
        out[f"size_{name}"] = pct.where(mask).median(axis=1).where(mask.sum(axis=1) >= MIN_BAND)

    # Yesterday's limit-ups today. The limit-ups and how many days in a row, from the limit events.
    stats, events = market._span_stats(dates)
    up = events[events["kind"] == "up"]
    lim = pd.DataFrame(False, index=pct.index, columns=pct.columns)
    if len(up):
        u = up[up["code"].isin(pct.columns) & up["date"].isin(pct.index)]
        lim = (u.assign(v=True).pivot_table(index="date", columns="code", values="v", aggfunc="any")
               .reindex(index=pct.index, columns=pct.columns).fillna(False).astype(bool))
    L = lim.to_numpy()
    streak = np.zeros(L.shape, dtype=np.int32)
    for i in range(len(dates)):
        streak[i] = np.where(L[i], (streak[i - 1] + 1) if i else 1, 0)
    out["height"] = streak.max(axis=1)
    out["multi_n"] = (streak >= 2).sum(axis=1)
    P = pct.to_numpy(dtype=float)
    rows = []
    for i in range(len(dates)):
        r = dict.fromkeys(["prem_n", "prem_avg", "prem_up", "promo_1", "promo_2", "promo_3", "promo_multi", "promo_all"])
        if i:
            prev = streak[i - 1]
            sel = prev >= 1
            today = P[i][sel]
            ok = ~np.isnan(today)
            r["prem_n"] = int(sel.sum())
            if ok.any():
                r["prem_avg"] = float(np.mean(today[ok]))
                r["prem_up"] = float(np.mean(today[ok] > 0) * 100)

            again = L[i]
            r["promo_1"], r["promo_2"], r["promo_3"] = _rate(again, prev == 1), _rate(again, prev == 2), _rate(again, prev >= 3)
            r["promo_multi"], r["promo_all"] = _rate(again, prev >= 2), _rate(again, prev >= 1)
        rows.append(r)
    out = out.join(pd.DataFrame(rows, index=pct.index))     # the first day has no yesterday: None
    out = out.join(_mood(out, stats.set_index("date") if len(stats) else pd.DataFrame()))
    return out[columns()]


def _mood(out: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    """The 情绪综合分 and its six parts, each 0–100 (None where a reading is missing)."""
    st = stats.reindex(out.index).apply(pd.to_numeric, errors="coerce") if len(stats) else pd.DataFrame(index=out.index)

    def ratio(a: str, b: str) -> pd.Series:
        if a not in st or b not in st:
            return pd.Series(np.nan, index=out.index)
        x, y = st[a], st[b]
        return (x / (x + y) * 100).where((x + y) > 0, 50.0)
    parts = pd.DataFrame({
        "m_updown": ratio("up", "down"),
        "m_limit": ratio("limit_up", "limit_down"),
        "m_seal": ratio("limit_up", "broken"),
        "m_prem": (50 + pd.to_numeric(out["prem_avg"], errors="coerce") * 10).clip(0, 100),
        "m_promo": (pd.to_numeric(out["promo_all"], errors="coerce") * 2.5).clip(0, 100),
        "m_height": ((pd.to_numeric(out["height"], errors="coerce") - 1) / 7 * 100).clip(0, 100),
    }, index=out.index)
    parts["mood"] = parts.mean(axis=1, skipna=True).where(parts.notna().sum(axis=1) >= 4)
    return parts


def _rate(again: np.ndarray, among: np.ndarray) -> float | None:
    """The share (%) of ``among`` that closed at the limit again; None when there are none."""
    return float(again[among].mean() * 100) if among.any() else None


def _key() -> tuple:
    return (market.base_through_day(), tuple(market.available_dates()))


def breadth(end: str | None = None, rng: str = "60d") -> dict:
    """The figures of each trading day in ``rng`` (as for the market stats) ending on ``end``."""
    if rng not in market.STATS_RANGES:
        raise ValueError(f"range must be one of {', '.join(market.STATS_RANGES)}")
    days = market._days_on_record(end)
    end = days[-1]
    start = market._range_start(end, rng, days)
    with _lock:
        table = _table(_key())
    part = table[(table.index >= start) & (table.index <= end)]

    def val(v):
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 3)
    cols = columns()
    out = [{"date": d, **{c: val(row[c]) for c in cols}} for d, row in part.iterrows()]
    return {"range": rng, "start": start, "end": end, "days": out,
            "bands": [{"name": b[0], "rule": BAND_RULES[b[0]]} for b in SIZE_BANDS]}


def invalidate() -> None:
    _table.cache_clear()

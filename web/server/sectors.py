"""Sectors and valuation, from 申万宏源研究's official daily index figures:

  rotation    each 申万一级 industry's daily change over the last N trading days to a day, and
              its compounded change over 5 and 20 days and over the N (the heat map);
  valuation   each industry's PE, PB and dividend yield on that day, with where each sits in
              its history since 2021 (the share of days at or below today's);
  crowding    行业拥挤度: each industry's share of the amount traded and turnover rate (5-day
              averages) ranked against its own history since 2021;
  market      申万A指's PE, PB and dividend yield every trading day since 2005, with China's
              10-year bond yield and 股债性价比 (the earnings yield 1/PE less that yield).

The series are the ones the data sync keeps (``ts/sw_daily``, ``ts/sw_market``), brought up
to date here at most once per closed trading day; when 申万 cannot be reached, what is on disk
is used and the reply says so.
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd

from tradingagents.dataflows.vendors.akshare import industry, settings as ak_settings, store
from tradingagents.dataflows.vendors.akshare.market import sw_index_analysis
from web.server import extras, market

ROTATION_DAYS = (10, 20)
_lock = threading.Lock()
_MEMO: dict[tuple[str, str], tuple[pd.DataFrame, str | None]] = {}


def _fetch(name: str) -> pd.DataFrame:
    today = store.now_cst().date()
    if name == "sw_daily":
        return store.incremental("sw_daily", industry._daily_fetcher("一级行业", today), "发布日期",
                                 f"{today.year - industry.L1_YEARS}0101", key_cols=("指数代码",))
    if name == "sw_daily2":
        return store.incremental("sw_daily2", industry._daily_fetcher("二级行业", today), "发布日期",
                                 f"{today.year - industry.L2_YEARS}0101", key_cols=("指数代码",))
    return store.incremental("sw_market", lambda s: sw_index_analysis("市场表征", "801003", s, today.strftime("%Y%m%d")),
                             "日期", ak_settings.START_DATE)


def series(name: str, fetch=None) -> tuple[pd.DataFrame, str | None]:
    """(the series with a ``date`` column YYYY-MM-DD, a note when it could not be brought up to date)."""
    fetch = fetch or _fetch
    key = (name, market.last_closed_day())
    with _lock:
        if key not in _MEMO:
            note = None
            try:
                df = fetch(name)
                if name in store.FALLBACKS:
                    note = f"申万数据未能更新：{store.FALLBACKS.pop(name)}"
            except Exception as e:  # noqa: BLE001 — a first download that failed: what is on disk, if any
                path = store.ts_path(name)
                if not path.exists():
                    raise LookupError(f"申万数据不可得：{type(e).__name__}") from e
                df, note = pd.read_parquet(path), f"申万数据未能更新，使用本地数据：{type(e).__name__}"
            col = "发布日期" if name.startswith("sw_daily") else "日期"
            df = df.assign(date=store.to_local_dates(df[col]).dt.strftime("%Y-%m-%d"))
            if len(_MEMO) > 8:          # older days' copies
                _MEMO.clear()
            _MEMO[key] = (df, note)
        return _MEMO[key]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _f(v) -> float:
    return float(pd.to_numeric(v, errors="coerce"))


def _rank(history: pd.Series, now: float) -> float | None:
    """The share (%) of the days in ``history`` at or below ``now`` (positive values only)."""
    h = history[history > 0].dropna()
    if not len(h) or not (now > 0):
        return None
    return round(float((h <= now).mean() * 100), 1)


def _r(v, d: int = 3):
    return None if v is None or pd.isna(v) else round(float(v), d)


LEVELS = {"sw1": "sw_daily", "sw2": "sw_daily2"}


def sectors(end: str | None = None, days: int = 20, level: str = "sw1") -> dict:
    """The industries' heat map over ``days`` trading days to ``end`` and their valuation on it:
    申万一级 (``sw1``) or 二级 (``sw2``, named 一级-二级; its history since 2023)."""
    if days not in ROTATION_DAYS:
        raise ValueError(f"days must be one of {', '.join(map(str, ROTATION_DAYS))}")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    df, note = series(LEVELS[level])
    if end:
        df = df[df["date"] <= end]
    if df.empty:
        raise FileNotFoundError(f"no 申万 industry data on or before {end}")
    as_of = df["date"].max()
    names = df.loc[df["date"] == as_of, "指数名称"].unique()       # today's classification
    df = df[df["指数名称"].isin(names)]
    pct = df.pivot_table(index="date", columns="指数名称", values="涨跌幅", aggfunc="last").sort_index()
    pct = pct.apply(pd.to_numeric, errors="coerce")
    window = pct.tail(max(days, 20))

    def comp(n: int) -> pd.Series:
        return ((1 + window.tail(n) / 100).prod() - 1) * 100

    c5, c20, cn = comp(5), comp(20), comp(days)
    shown = window.tail(days)
    today = df[df["date"] == as_of].set_index("指数名称")
    out = []
    for name in names:
        hist = df[df["指数名称"] == name]
        pe, pb = _num(hist["市盈率"]), _num(hist["市净率"])
        row = today.loc[name]
        now_pe, now_pb = _f(row["市盈率"]), _f(row["市净率"])
        code = str(row["指数代码"])
        parent = industry.SW2_PARENT.get(code) if level == "sw2" else None
        out.append({
            "name": f"{parent}-{name}" if parent else name, "code": code, "sw1": parent or name,
            "pct": [_r(v, 2) for v in shown[name].tolist()],
            "cum": _r(cn[name], 2), "cum5": _r(c5[name], 2), "cum20": _r(c20[name], 2),
            "pe": _r(now_pe, 2), "pb": _r(now_pb, 2), "dy": _r(_f(row["股息率"]), 2),
            "pe_rank": _rank(pe, now_pe), "pb_rank": _rank(pb, now_pb),
            "amount_share": _r(_f(row["成交额占比"]), 2),
        })
    out.sort(key=lambda x: -(x["cum"] if x["cum"] is not None else -np.inf))
    return {"end": end, "as_of": as_of, "days": days, "level": level, "dates": list(shown.index), "industries": out,
            "since": df["date"].min(), "note": note}


def valuation(end: str | None = None) -> dict:
    """申万A指's PE, PB and dividend yield on every trading day to ``end``."""
    df, note = series("sw_market")
    if end:
        df = df[df["date"] <= end]
    if df.empty:
        raise FileNotFoundError(f"no 申万A指 data on or before {end}")
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    pe, pb, dy = _num(df["市盈率"]), _num(df["市净率"]), _num(df["股息率"])
    # 股债性价比: the earnings yield (1 / PE) less the 10-year government bond yield, on the
    # last yield published on or before each day.
    y10, bond_note = extras.bond10()
    y = y10.reindex(sorted(set(y10.index) | set(df["date"]))).ffill().reindex(df["date"]).to_numpy()
    erp = 100 / pe.where(pe > 0) - y
    return {"end": end, "as_of": df["date"].iat[-1], "note": note or bond_note,
            "days": [{"date": d, "pe": _r(a, 2), "pb": _r(b, 3), "dy": _r(c, 2), "y10": _r(t, 3), "erp": _r(e, 3)}
                     for d, a, b, c, t, e in zip(df["date"], pe, pb, dy, y, erp, strict=False)]}


def invalidate() -> None:
    with _lock:
        _MEMO.clear()


CROWD_SMOOTH = 5            # days averaged before ranking, so one busy day does not decide it


def crowding(end: str | None = None) -> dict:
    """行业拥挤度: each 申万一级 industry's share of the market's amount traded and its turnover
    rate, each averaged over the last CROWD_SMOOTH trading days and ranked (%) against the
    industry's own history since 2021 (the same average on every day); 拥挤度 is the mean of
    the two ranks. With the industry's change over 20 days and how its share moved."""
    df, note = series("sw_daily")
    if end:
        df = df[df["date"] <= end]
    if df.empty:
        raise FileNotFoundError(f"no 申万 industry data on or before {end}")
    as_of = df["date"].max()
    names = df.loc[df["date"] == as_of, "指数名称"].unique()
    df = df[df["指数名称"].isin(names)]

    def wide(col: str) -> pd.DataFrame:
        return df.pivot_table(index="date", columns="指数名称", values=col, aggfunc="last").sort_index().apply(pd.to_numeric, errors="coerce")
    share, turn, pct = wide("成交额占比"), wide("换手率"), wide("涨跌幅")
    s5 = share.rolling(CROWD_SMOOTH, min_periods=CROWD_SMOOTH).mean()
    t5 = turn.rolling(CROWD_SMOOTH, min_periods=CROWD_SMOOTH).mean()
    c20 = ((1 + pct.tail(20) / 100).prod() - 1) * 100
    out = []
    for name in names:
        hs, ht = s5[name].dropna(), t5[name].dropna()
        if not len(hs) or not len(ht):
            continue
        rs = float((hs <= hs.iat[-1]).mean() * 100)
        rt = float((ht <= ht.iat[-1]).mean() * 100)
        prev = hs.iloc[-21] if len(hs) > 20 else None
        out.append({"name": name, "share": _r(share[name].iat[-1], 2), "share5": _r(hs.iat[-1], 2),
                    "share5_20d": _r(prev, 2), "share_rank": round(rs, 1),
                    "turnover5": _r(ht.iat[-1], 2), "turnover_rank": round(rt, 1),
                    "crowd": round((rs + rt) / 2, 1), "cum20": _r(c20.get(name), 2)})
    out.sort(key=lambda x: -x["crowd"])
    return {"end": end, "as_of": as_of, "since": df["date"].min(), "smooth": CROWD_SMOOTH, "industries": out, "note": note}

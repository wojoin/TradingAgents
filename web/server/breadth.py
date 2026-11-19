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
  分板块      the median change of 主板, 创业板, 科创板 and 北交所 stocks.
  成交集中度  the share of the day's amount traded taken by the 100 busiest stocks, and by the
              busiest 5% of stocks.
  TRIN        the Arms index: (rising ÷ falling stocks) ÷ (the rising stocks' amount traded ÷ the
              falling stocks'), TRIN_额; with volume instead of amount, TRIN_量; each also as
              its 10-day average and where that sits among the past 250 days (%). Under 1: the
              money is on the rising side; in A-shares it is so most days, hence the percentile.
  麦克连      the McClellan oscillator, ratio-adjusted: each day's (rising − falling) ÷ (rising +
              falling) × 1000, its 19-day EMA less its 39-day EMA.
  MSI         the McClellan summation index: the oscillator added up. Summed from the first day
              kept, its zero line would depend on that day. With α = 2 / (n + 1), Σ EMAₙ = X − (1/α − 1)
              EMAₙ + c, so the running sum of EMA19 − EMA39 is 19 × EMA39 − 9 × EMA19 plus a
              constant fixed by the start: that closed form is the sum taken from the start of time,
              and its sign means something (in a steady state it is 10 × the net advance ratio).
              msi_cross: +1 / −1 on the days it turns positive / negative.
  涨跌比 ADR  rising ÷ falling stocks, its 10-day average and where that sits among 250 days.
  绝对广量 ABI |rising − falling| ÷ (rising + falling) (%): how one-sided the day was, either way.
  广度推力    Zweig's breadth thrust: the 10-day EMA of rising ÷ (rising + falling); a signal
              when it climbs from under 0.40 to over 0.615 within 10 trading days.
  涨跌量比    the rising stocks' amount traded (and volume) ÷ the falling stocks'.
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

PANEL_VERSION = 3              # 2: with the amount traded; 3: and the volume
LOOKBACK = 520                 # trading days of base kept: 250-day highs over a year's range
SIZE_BANDS = (("大盘", 0, 300), ("中盘", 300, 800), ("小盘", 800, 1800), ("微盘", -400, None))
BAND_RULES = {"大盘": "流通市值前 300（≈沪深300）", "中盘": "第 301–800（≈中证500）",
              "小盘": "第 801–1800（≈中证1000）", "微盘": "最小的 400 只"}
MIN_STOCKS = 100              # fewer stocks with enough history on a day: no breadth figure
MIN_BAND = 50                 # fewer stocks in a size band on a day: no median
MIN_BOARD = 20                # fewer stocks of a board on a day: no median
MIN_MARKET = 500              # fewer stocks traded on a day: no TRIN, McClellan or concentration
_FIXED = ["prem_n", "prem_avg", "prem_up", "promo_1", "promo_2", "promo_3", "promo_multi", "promo_all",
          "nh60", "nl60", "nh250", "nl250", "ma20", "ma60", "height", "multi_n",
          "mood", *[f"m_{k}" for k in ("updown", "limit", "seal", "prem", "promo", "height")],
          "conc100", "conc5pct", "amount", *[f"board_{b}" for b in ("主板", "创业板", "科创板", "北交所")],
          "trin_amt", "trin_vol", "trin_amt10", "trin_vol10", "trin_amt10_rank", "trin_vol10_rank",
          "mcl_osc", "mcl_sum", "mcl_ratio", "msi_cross", "ma250", "adr", "adr10", "adr10_rank", "abi", "abi10",
          "thrust", "thrust_signal", "ud_amt", "ud_vol"]
THRUST_LOW, THRUST_HIGH, THRUST_DAYS = 0.40, 0.615, 10
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
        return pd.DataFrame(columns=["date", "code", "name", "pct_chg", "close", "amount", "volume"])
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
        "amount": pd.to_numeric(rows["amount"], errors="coerce").astype("float64"),
        "volume": pd.to_numeric(rows["volume"], errors="coerce").astype("float64"),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob("panel_v*_*.parquet"):      # an older version, or base moved on: one kept
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
                                   "close": pd.to_numeric(xs["close"], errors="coerce"),
                                   "amount": pd.to_numeric(xs["amount"], errors="coerce"),
                                   "volume": pd.to_numeric(xs["volume"], errors="coerce")}))
        if "float_mv" in xs:
            mv_parts.append(pd.DataFrame({"date": d, "code": code, "mv": pd.to_numeric(xs["float_mv"], errors="coerce")}))
    panel = pd.concat([p for p in parts if len(p)], ignore_index=True)
    panel = panel[panel["close"] > 0]
    if panel.empty:
        return pd.DataFrame(columns=columns())
    pct, close, amt = _wide(panel, "pct_chg"), _wide(panel, "close"), _wide(panel, "amount")
    vol = _wide(panel, "volume") if "volume" in panel else pd.DataFrame(index=pct.index, columns=pct.columns)
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
    for n in (20, 60, 250):
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

    # 成交集中度: the 100 busiest stocks' share, and the busiest 5%'s.
    a = amt.reindex(columns=pct.columns).where(traded)
    total = a.sum(axis=1)
    ranked = a.rank(axis=1, ascending=False, method="first")
    n = a.notna().sum(axis=1)
    out["amount"] = total.where(total > 0)
    out["conc100"] = (a.where(ranked <= 100).sum(axis=1) / total * 100).where(n >= MIN_MARKET)
    out["conc5pct"] = (a.where(ranked.le(n * 0.05, axis=0)).sum(axis=1) / total * 100).where(n >= MIN_MARKET)

    # TRIN (Arms index): the rising/falling count ratio over their amount (or volume) ratio.
    rising, falling = pct > 0, pct < 0
    adv, dec = rising.sum(axis=1), falling.sum(axis=1)
    for key, w in (("amt", a), ("vol", vol.reindex(index=pct.index, columns=pct.columns).where(traded))):
        up_w, down_w = w.where(rising).sum(axis=1), w.where(falling).sum(axis=1)
        ok = (adv > 0) & (dec > 0) & (up_w > 0) & (down_w > 0) & (n >= MIN_MARKET)
        trin = ((adv / dec) / (up_w / down_w)).where(ok)
        out[f"trin_{key}"] = trin
        out[f"ud_{key}"] = (up_w / down_w).where(ok)                        # 涨跌成交额比 / 成交量比
        out[f"trin_{key}10"] = avg = trin.rolling(10, min_periods=10).mean()
        # In A-shares the few rising stocks often take more than their share of the money, so
        # TRIN sits under 1 most days: read it against its own past 250 days, not against 1.
        out[f"trin_{key}10_rank"] = avg.rolling(250, min_periods=60).apply(lambda x: (x <= x[-1]).mean() * 100, raw=True)
    # 涨跌比 ADR, 绝对广量 ABI and Zweig's breadth thrust.
    whole = (adv + dec) >= MIN_MARKET
    adr = (adv / dec).where(whole & (dec > 0))
    out["adr"] = adr
    out["adr10"] = adr10 = adr.rolling(10, min_periods=10).mean()
    out["adr10_rank"] = adr10.rolling(250, min_periods=60).apply(lambda x: (x <= x[-1]).mean() * 100, raw=True)
    out["abi"] = abi = ((adv - dec).abs() / (adv + dec) * 100).where(whole)
    out["abi10"] = abi.rolling(10, min_periods=10).mean()
    thrust = (adv / (adv + dec)).where(whole).ewm(span=THRUST_DAYS, adjust=False).mean()
    out["thrust"] = thrust.where(whole)
    out["thrust_signal"] = thrust_signals(thrust)

    # McClellan, ratio-adjusted: 19- and 39-day EMAs of (rising - falling) / (rising + falling) * 1000.
    ratio = ((adv - dec) / (adv + dec) * 1000).where((adv + dec) >= MIN_MARKET)
    e19, e39 = ratio.ewm(span=19, adjust=False).mean(), ratio.ewm(span=39, adjust=False).mean()
    out["mcl_ratio"] = ratio
    out["mcl_osc"] = (e19 - e39).where(ratio.notna())
    msi = (19 * e39 - 9 * e19).where(ratio.notna())      # MSI, the summation from the start of time
    out["mcl_sum"] = msi
    sign = np.sign(msi)
    out["msi_cross"] = (sign.where((sign != sign.shift(1)) & sign.shift(1).notna() & (sign != 0))).fillna(0)

    # 分板块: each board's median change.
    boards = market.board_of(pd.Series(pct.columns, index=pct.columns))
    for b in ("主板", "创业板", "科创板", "北交所"):
        cols = boards.index[boards == b]
        out[f"board_{b}"] = pct[cols].median(axis=1).where(traded[cols].sum(axis=1) >= MIN_BOARD) if len(cols) else np.nan
    return out[columns()]


def thrust_signals(thrust: pd.Series) -> pd.Series:
    """Zweig's breadth thrust: the days the EMA closes above THRUST_HIGH having been under
    THRUST_LOW within the last THRUST_DAYS days. A thrust fires once: another needs the EMA
    to fall under THRUST_LOW again first (a dip under the high mark is the same thrust)."""
    out = pd.Series(False, index=thrust.index)
    armed_until = -1
    for i, v in enumerate(thrust.to_numpy()):
        if np.isnan(v):
            continue
        if v < THRUST_LOW:
            armed_until = i + THRUST_DAYS
        elif v > THRUST_HIGH and i <= armed_until:
            out.iat[i] = True
            armed_until = -1
    return out


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
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 3)
    cols = columns()
    out = [{"date": d, **{c: val(row[c]) for c in cols}} for d, row in part.iterrows()]
    return {"range": rng, "start": start, "end": end, "days": out,
            "bands": [{"name": b[0], "rule": BAND_RULES[b[0]]} for b in SIZE_BANDS]}


def invalidate() -> None:
    _table.cache_clear()

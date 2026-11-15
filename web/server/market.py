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

import pandas as pd

from tradingagents.dataflows.symbols import a_share_code, normalize_symbol
from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store

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
        return flow, {"source": "eastmoney", "label": "主力净流入", "note": "东方财富 今日主力净流入"}
    ths = _cached_table("ths_fund_flow_now", key)
    if ths is None and latest:
        try:
            ths = _dated("ths_fund_flow_now", key, final,
                         lambda: store.ak().stock_fund_flow_individual(symbol="即时"), "同花顺 fund flow")
        except Exception:  # noqa: BLE001
            ths = None
    if ths is not None and len(ths) and "净额" in ths:
        flow = ths["净额"].map(cn_number)
        flow.index = ths["股票代码"].astype(str).str.zfill(6)
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


def trading_days() -> list[str]:
    """Trading days (YYYY-MM-DD) up to the latest one on disk, oldest first."""
    dates = available_dates()
    if not dates:
        return []
    cal = [f"{d:%Y-%m-%d}" for d in store.trade_calendar()]
    latest = dates[0]
    days = [d for d in cal if d <= latest]
    return sorted(set(days) | set(dates))


def calendar() -> dict:
    """The date picker's bounds: first and last trading day, and the weekdays in between that
    are not trading days (holidays), so only trading days can be picked."""
    days = trading_days()
    if not days:
        return {"min": None, "max": None, "latest": None, "holidays": []}
    trading = set(days)
    weekdays = pd.bdate_range(days[0], days[-1])
    holidays = [f"{d:%Y-%m-%d}" for d in weekdays if f"{d:%Y-%m-%d}" not in trading]
    return {"min": days[0], "max": days[-1], "latest": available_dates()[0], "holidays": holidays}


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
